"""
Business logic for Production Orders, Order Operations, Status Lifecycle,
and Sequence-Dependent Changeover Matrix.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    ChangeoverMatrix,
    MaterialRequirement,
    Product,
    ProductionOrder,
    ProductionOrderOperation,
    Routing,
    RoutingOperation,
)
from app.models.enums import OperationExecutionStatus, OrderStatus
from app.schemas.orders import (
    ChangeoverUpsert,
    OrderCreate,
    OrderOperationProgressUpdate,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services.audit_service import record_audit_log, record_state_change
from app.utils.id_generator import (
    format_order_id,
    format_order_operation_id,
    next_numeric_suffix,
)
from app.utils.lifecycle import is_valid_order_transition


def list_orders(
    db: Session,
    search: str | None = None,
    status_filter: str | None = None,
    priority: int | None = None,
    sort_by: str = "order_id",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[ProductionOrder]]:
    query = db.query(ProductionOrder)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (ProductionOrder.order_id.ilike(like))
            | (ProductionOrder.product_id.ilike(like))
            | (ProductionOrder.customer_name.ilike(like))
        )
    if status_filter:
        query = query.filter(ProductionOrder.status == status_filter)
    if priority is not None:
        query = query.filter(ProductionOrder.priority == priority)

    sort_col_map = {
        "order_id": ProductionOrder.order_id,
        "priority": ProductionOrder.priority,
        "due_date": ProductionOrder.due_date,
        "release_date": ProductionOrder.release_date,
        "status": ProductionOrder.status,
    }
    col = sort_col_map.get(sort_by, ProductionOrder.order_id)
    query = query.order_by(col.desc() if sort_dir.lower() == "desc" else col.asc())

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


def create_order(db: Session, payload: OrderCreate, username: str = "system") -> ProductionOrder:
    product = db.query(Product).filter(Product.product_id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{payload.product_id}' not found.")
    if payload.due_date <= payload.release_date:
        raise HTTPException(status_code=400, detail="due_date must be after release_date.")

    if payload.routing_id:
        routing = db.query(Routing).filter(Routing.routing_id == payload.routing_id).first()
    else:
        routing = (
            db.query(Routing)
            .filter(Routing.product_id == payload.product_id, Routing.is_active == True)  # noqa: E712
            .first()
        )
    if not routing or routing.product_id != product.product_id:
        raise HTTPException(status_code=400, detail="Valid active routing for this product is required.")

    counter = next_numeric_suffix(db, ProductionOrder, ProductionOrder.order_id, "ORD-2026-")
    order_id = format_order_id(counter, 2026)

    order = ProductionOrder(
        order_id=order_id,
        product_id=product.product_id,
        routing_id=routing.routing_id,
        quantity=payload.quantity,
        completed_quantity=0,
        priority=payload.priority,
        customer_name=payload.customer_name,
        release_date=payload.release_date,
        due_date=payload.due_date,
        is_urgent=(payload.priority == 1),
        status=OrderStatus.DRAFT.value,
        notes=payload.notes,
    )
    db.add(order)
    db.flush()

    # Expand routing steps into concrete order operations
    routing_steps = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.sequence_number)
        .all()
    )
    for step in routing_steps:
        planned_mins = max(5, int(round(step.duration_per_unit_minutes * payload.quantity)))
        db.add(
            ProductionOrderOperation(
                operation_id=format_order_operation_id(order_id, step.sequence_number),
                order_id=order_id,
                routing_operation_id=step.id,
                operation_code=step.operation_code,
                sequence_number=step.sequence_number,
                planned_duration_minutes=planned_mins,
                setup_minutes=step.setup_minutes,
                labor_required=step.labor_required,
                tooling_id=step.tooling_id,
                status=OperationExecutionStatus.PENDING.value,
            )
        )

    record_state_change(
        db,
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        previous_state=None,
        new_state=OrderStatus.DRAFT.value,
        changed_by=username,
        reason="Order created",
    )
    record_audit_log(
        db,
        username=username,
        action="CREATE_ORDER",
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        new_value={"product_id": order.product_id, "quantity": order.quantity},
    )
    db.commit()
    db.refresh(order)
    return order


def get_order_detail(db: Session, order_id: str) -> dict:
    order = db.query(ProductionOrder).filter(ProductionOrder.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Production order '{order_id}' not found.")

    ops = (
        db.query(ProductionOrderOperation)
        .filter(ProductionOrderOperation.order_id == order_id)
        .order_by(ProductionOrderOperation.sequence_number)
        .all()
    )
    boms = (
        db.query(MaterialRequirement)
        .filter(MaterialRequirement.product_id == order.product_id)
        .all()
    )
    return {
        "order": order,
        "operations": ops,
        "material_requirements": [
            {
                "material_id": b.material_id,
                "operation_code": b.operation_code,
                "quantity_per_unit": b.quantity_per_unit,
                "total_required_quantity": round(
                    b.quantity_per_unit * order.quantity * (1.0 + b.scrap_factor), 2
                ),
            }
            for b in boms
        ],
    }


def update_order(
    db: Session, order_id: str, payload: OrderUpdate, username: str = "system"
) -> ProductionOrder:
    order = db.query(ProductionOrder).filter(ProductionOrder.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Production order '{order_id}' not found.")

    updates = payload.model_dump(exclude_unset=True)
    new_rel = updates.get("release_date", order.release_date)
    new_due = updates.get("due_date", order.due_date)
    if new_due <= new_rel:
        raise HTTPException(status_code=400, detail="due_date must be after release_date.")

    old_val = {"quantity": order.quantity, "priority": order.priority}
    for field, val in updates.items():
        setattr(order, field, val)
    if "priority" in updates:
        order.is_urgent = order.priority == 1

    record_audit_log(
        db,
        username=username,
        action="UPDATE_ORDER",
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        old_value=old_val,
        new_value=updates,
    )
    db.commit()
    db.refresh(order)
    return order


def transition_order_status(
    db: Session, order_id: str, payload: OrderStatusUpdate, username: str = "system"
) -> ProductionOrder:
    order = db.query(ProductionOrder).filter(ProductionOrder.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=f"Production order '{order_id}' not found.")

    if payload.new_status not in {e.value for e in OrderStatus}:
        raise HTTPException(status_code=400, detail=f"Invalid order status '{payload.new_status}'.")

    if not is_valid_order_transition(order.status, payload.new_status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid lifecycle transition from '{order.status}' to '{payload.new_status}'.",
        )

    prev_status = order.status
    order.status = payload.new_status
    record_state_change(
        db,
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        previous_state=prev_status,
        new_state=payload.new_status,
        changed_by=username,
        reason=payload.reason,
    )
    record_audit_log(
        db,
        username=username,
        action="CHANGE_ORDER_STATUS",
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        old_value=prev_status,
        new_value=payload.new_status,
        reason=payload.reason,
    )
    db.commit()
    db.refresh(order)
    return order


def update_operation_progress(
    db: Session,
    operation_id: str,
    payload: OrderOperationProgressUpdate,
    username: str = "operator",
) -> ProductionOrderOperation:
    op = (
        db.query(ProductionOrderOperation)
        .filter(ProductionOrderOperation.operation_id == operation_id)
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")

    order = db.query(ProductionOrder).filter(ProductionOrder.order_id == op.order_id).first()
    if payload.completed_quantity > order.quantity:
        raise HTTPException(status_code=400, detail="completed_quantity cannot exceed order quantity.")

    old_status = op.status
    op.completed_quantity = payload.completed_quantity
    if payload.status:
        op.status = payload.status
    elif payload.completed_quantity >= order.quantity:
        op.status = OperationExecutionStatus.COMPLETED.value
    elif payload.completed_quantity > 0:
        op.status = OperationExecutionStatus.IN_PROGRESS.value

    record_audit_log(
        db,
        username=username,
        action="UPDATE_OPERATION_PROGRESS",
        entity_type="ProductionOrderOperation",
        entity_id=op.operation_id,
        old_value={"status": old_status},
        new_value={"status": op.status, "completed_quantity": op.completed_quantity},
        reason=payload.notes,
    )
    db.commit()
    db.refresh(op)
    return op


def upsert_changeover(
    db: Session, payload: ChangeoverUpsert, username: str = "system"
) -> ChangeoverMatrix:
    if payload.from_product_id == payload.to_product_id and payload.changeover_minutes != 0:
        raise HTTPException(status_code=400, detail="Same-product changeover must be 0 minutes.")

    existing = (
        db.query(ChangeoverMatrix)
        .filter(
            ChangeoverMatrix.machine_id == payload.machine_id,
            ChangeoverMatrix.from_product_id == payload.from_product_id,
            ChangeoverMatrix.to_product_id == payload.to_product_id,
        )
        .first()
    )
    if existing:
        old_mins = existing.changeover_minutes
        existing.changeover_minutes = payload.changeover_minutes
        existing.cleaning_required = payload.cleaning_required
        existing.notes = payload.notes
        record_audit_log(
            db,
            username=username,
            action="UPDATE_CHANGEOVER",
            entity_type="ChangeoverMatrix",
            entity_id=str(existing.id),
            old_value={"changeover_minutes": old_mins},
            new_value={"changeover_minutes": payload.changeover_minutes},
        )
        db.commit()
        db.refresh(existing)
        return existing

    entry = ChangeoverMatrix(**payload.model_dump())
    db.add(entry)
    db.flush()
    record_audit_log(
        db,
        username=username,
        action="CREATE_CHANGEOVER",
        entity_type="ChangeoverMatrix",
        entity_id=str(entry.id),
        new_value=payload.model_dump(),
    )
    db.commit()
    db.refresh(entry)
    return entry

