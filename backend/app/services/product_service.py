"""
Business logic for Products, Routings, Operations, Machine Eligibility, and BOMs.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    Material,
    MaterialRequirement,
    Operation,
    OperationMachineEligibility,
    Product,
    Routing,
    RoutingOperation,
)
from app.models.enums import ProductStatus
from app.schemas.products import (
    MaterialRequirementCreate,
    ProductCreate,
    ProductUpdate,
    RoutingCreate,
)
from app.services.audit_service import record_audit_log
from app.utils.id_generator import (
    format_product_id,
    format_routing_id,
    next_numeric_suffix,
)


def list_products(
    db: Session,
    search: str | None = None,
    category: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Product]]:
    query = db.query(Product)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Product.product_id.ilike(like))
            | (Product.sku.ilike(like))
            | (Product.name.ilike(like))
        )
    if category:
        query = query.filter(Product.category == category)
    if status_filter:
        query = query.filter(Product.status == status_filter)

    total = query.count()
    items = (
        query.order_by(Product.product_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def create_product(db: Session, payload: ProductCreate, username: str = "system") -> Product:
    existing_sku = db.query(Product).filter(Product.sku == payload.sku.upper()).first()
    if existing_sku:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product with SKU '{payload.sku}' already exists.",
        )

    counter = next_numeric_suffix(db, Product, Product.product_id, "PROD-2026-")
    product = Product(
        product_id=format_product_id(counter, 2026),
        sku=payload.sku.upper(),
        name=payload.name,
        category=payload.category,
        unit_of_measure=payload.unit_of_measure,
        standard_batch_size=payload.standard_batch_size,
        description=payload.description,
        status=ProductStatus.ACTIVE.value,
    )
    db.add(product)
    record_audit_log(
        db,
        username=username,
        action="CREATE_PRODUCT",
        entity_type="Product",
        entity_id=product.product_id,
        new_value={"sku": product.sku, "name": product.name},
    )
    db.commit()
    db.refresh(product)
    return product


def get_product_detail(db: Session, product_id: str) -> dict:
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")

    routings = db.query(Routing).filter(Routing.product_id == product_id).all()
    bom = (
        db.query(MaterialRequirement)
        .filter(MaterialRequirement.product_id == product_id)
        .all()
    )
    return {
        "product": product,
        "routings": [build_routing_detail(db, r) for r in routings],
        "material_requirements": [
            {
                "id": mr.id,
                "material_id": mr.material_id,
                "operation_code": mr.operation_code,
                "quantity_per_unit": mr.quantity_per_unit,
                "scrap_factor": mr.scrap_factor,
            }
            for mr in bom
        ],
    }


def update_product(
    db: Session, product_id: str, payload: ProductUpdate, username: str = "system"
) -> Product:
    product = db.query(Product).filter(Product.product_id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")

    old_snapshot = {"name": product.name, "status": product.status}
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "status" and value not in {e.value for e in ProductStatus}:
            raise HTTPException(status_code=400, detail=f"Invalid product status '{value}'.")
        setattr(product, field, value)

    record_audit_log(
        db,
        username=username,
        action="UPDATE_PRODUCT",
        entity_type="Product",
        entity_id=product.product_id,
        old_value=old_snapshot,
        new_value=payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(product)
    return product


def build_routing_detail(db: Session, routing: Routing) -> dict:
    """Return routing along with ordered steps and eligible machines per step."""
    steps_out = []
    steps = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.sequence_number)
        .all()
    )
    for step in steps:
        op = db.query(Operation).filter(Operation.operation_code == step.operation_code).first()
        elig = (
            db.query(OperationMachineEligibility.machine_id)
            .filter(OperationMachineEligibility.operation_code == step.operation_code)
            .all()
        )
        steps_out.append(
            {
                "id": step.id,
                "routing_id": step.routing_id,
                "operation_code": step.operation_code,
                "sequence_number": step.sequence_number,
                "duration_per_unit_minutes": step.duration_per_unit_minutes,
                "setup_minutes": step.setup_minutes,
                "labor_required": step.labor_required,
                "tooling_id": step.tooling_id,
                "operation_name": op.name if op else None,
                "operation_type": op.operation_type if op else None,
                "eligible_machines": [row[0] for row in elig],
            }
        )
    return {
        "routing_id": routing.routing_id,
        "product_id": routing.product_id,
        "version": routing.version,
        "name": routing.name,
        "is_active": routing.is_active,
        "effective_from": routing.effective_from,
        "effective_to": routing.effective_to,
        "status": routing.status,
        "steps": steps_out,
    }


def create_routing(db: Session, payload: RoutingCreate, username: str = "system") -> dict:
    product = db.query(Product).filter(Product.product_id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{payload.product_id}' not found.")

    if payload.effective_from and payload.effective_to and payload.effective_to < payload.effective_from:
        raise HTTPException(status_code=400, detail="effective_to must be on or after effective_from.")

    seqs = sorted(step.sequence_number for step in payload.steps)
    if seqs != list(range(1, len(seqs) + 1)):
        raise HTTPException(
            status_code=400,
            detail="Operation sequence numbers must be continuous starting at 1 (e.g., 1, 2, 3).",
        )

    routing_id = format_routing_id(product.sku, payload.version)
    if db.query(Routing).filter(Routing.routing_id == routing_id).first():
        raise HTTPException(status_code=409, detail=f"Routing '{routing_id}' already exists.")

    routing = Routing(
        routing_id=routing_id,
        product_id=product.product_id,
        version=payload.version,
        name=payload.name,
        is_active=True,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        status="Active",
    )
    db.add(routing)
    db.flush()

    for step in payload.steps:
        op = db.query(Operation).filter(Operation.operation_code == step.operation_code).first()
        if not op:
            raise HTTPException(status_code=404, detail=f"Operation '{step.operation_code}' not found.")
        db.add(
            RoutingOperation(
                routing_id=routing.routing_id,
                operation_code=step.operation_code,
                sequence_number=step.sequence_number,
                duration_per_unit_minutes=step.duration_per_unit_minutes,
                setup_minutes=step.setup_minutes,
                labor_required=step.labor_required,
                tooling_id=step.tooling_id or op.tooling_id,
            )
        )

    record_audit_log(
        db,
        username=username,
        action="CREATE_ROUTING",
        entity_type="Routing",
        entity_id=routing.routing_id,
        new_value={"steps": len(payload.steps)},
    )
    db.commit()
    db.refresh(routing)
    return build_routing_detail(db, routing)


def add_material_requirement(
    db: Session, payload: MaterialRequirementCreate, username: str = "system"
) -> MaterialRequirement:
    if not db.query(Product).filter(Product.product_id == payload.product_id).first():
        raise HTTPException(status_code=404, detail=f"Product '{payload.product_id}' not found.")
    if not db.query(Material).filter(Material.material_id == payload.material_id).first():
        raise HTTPException(status_code=404, detail=f"Material '{payload.material_id}' not found.")

    mr = MaterialRequirement(
        product_id=payload.product_id,
        operation_code=payload.operation_code,
        material_id=payload.material_id,
        quantity_per_unit=payload.quantity_per_unit,
        scrap_factor=payload.scrap_factor,
    )
    db.add(mr)
    record_audit_log(
        db,
        username=username,
        action="ADD_MATERIAL_REQUIREMENT",
        entity_type="Product",
        entity_id=payload.product_id,
        new_value={"material_id": payload.material_id, "qty_per_unit": payload.quantity_per_unit},
    )
    db.commit()
    db.refresh(mr)
    return mr

