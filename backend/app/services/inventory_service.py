"""
Business logic for Materials, Inventory Lots, Reservations, Consumption,
Shortage Detection, and Reconciliation.

Important Rule: Negative inventory is NEVER allowed during normal operations.
"""

from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import InventoryLot, Material, MaterialRequirement, ProductionOrder
from app.models.enums import OrderStatus, StockStatus
from app.schemas.materials import (
    InventoryActionRequest,
    InventoryLotCreate,
    MaterialCreate,
    MaterialUpdate,
)
from app.services.audit_service import record_audit_log
from app.utils.id_generator import format_material_id, next_numeric_suffix


def recalculate_material_totals(db: Session, material: Material) -> Material:
    """Recompute material stock totals and `stock_status` from its inventory lots."""
    lots = db.query(InventoryLot).filter(InventoryLot.material_id == material.material_id).all()
    material.available_quantity = round(sum(l.available_quantity for l in lots), 2)
    material.reserved_quantity = round(sum(l.reserved_quantity for l in lots), 2)
    material.consumed_quantity = round(sum(l.consumed_quantity for l in lots), 2)

    has_delay = any(l.is_delayed and l.available_quantity > 0 for l in lots)
    if material.available_quantity <= 0:
        material.stock_status = StockStatus.OUT_OF_STOCK.value
    elif has_delay:
        material.stock_status = StockStatus.DELAYED.value
    elif material.available_quantity < material.reorder_level:
        material.stock_status = StockStatus.LOW_STOCK.value
    else:
        material.stock_status = StockStatus.IN_STOCK.value
    return material


def create_material(db: Session, payload: MaterialCreate, username: str = "system") -> Material:
    counter = next_numeric_suffix(db, Material, Material.material_id, "MAT-2026-")
    mat = Material(
        material_id=format_material_id(counter, 2026),
        name=payload.name,
        category=payload.category,
        unit=payload.unit,
        unit_cost=payload.unit_cost,
        reorder_level=payload.reorder_level,
        available_quantity=0.0,
        reserved_quantity=0.0,
        consumed_quantity=0.0,
        stock_status=StockStatus.OUT_OF_STOCK.value,
        status="Active",
    )
    db.add(mat)
    record_audit_log(
        db,
        username=username,
        action="CREATE_MATERIAL",
        entity_type="Material",
        entity_id=mat.material_id,
        new_value={"name": mat.name, "unit": mat.unit},
    )
    db.commit()
    db.refresh(mat)
    return mat


def update_material(
    db: Session, material_id: str, payload: MaterialUpdate, username: str = "system"
) -> Material:
    mat = db.query(Material).filter(Material.material_id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail=f"Material '{material_id}' not found.")

    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(mat, field, val)
    recalculate_material_totals(db, mat)
    record_audit_log(
        db,
        username=username,
        action="UPDATE_MATERIAL",
        entity_type="Material",
        entity_id=mat.material_id,
        new_value=payload.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(mat)
    return mat


def receive_inventory_lot(
    db: Session, payload: InventoryLotCreate, username: str = "system"
) -> InventoryLot:
    mat = db.query(Material).filter(Material.material_id == payload.material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail=f"Material '{payload.material_id}' not found.")
    if db.query(InventoryLot).filter(InventoryLot.lot_number == payload.lot_number).first():
        raise HTTPException(status_code=409, detail=f"Lot '{payload.lot_number}' already exists.")
    if payload.expiry_date and payload.expiry_date <= payload.availability_date:
        raise HTTPException(status_code=400, detail="expiry_date must be after availability_date.")

    lot = InventoryLot(
        material_id=payload.material_id,
        lot_number=payload.lot_number,
        initial_quantity=payload.quantity,
        available_quantity=payload.quantity,
        reserved_quantity=0.0,
        consumed_quantity=0.0,
        availability_date=payload.availability_date,
        expiry_date=payload.expiry_date,
        supplier_name=payload.supplier_name,
        is_delayed=payload.is_delayed,
        status="Delayed" if payload.is_delayed else "Available",
    )
    db.add(lot)
    db.flush()
    recalculate_material_totals(db, mat)
    record_audit_log(
        db,
        username=username,
        action="RECEIVE_INVENTORY",
        entity_type="InventoryLot",
        entity_id=lot.lot_number,
        new_value={"material_id": mat.material_id, "quantity": payload.quantity},
    )
    db.commit()
    db.refresh(lot)
    return lot


def reserve_inventory(
    db: Session, payload: InventoryActionRequest, username: str = "system"
) -> Material:
    mat = db.query(Material).filter(Material.material_id == payload.material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail=f"Material '{payload.material_id}' not found.")
    if mat.available_quantity < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient available stock for '{mat.material_id}': "
                f"requested {payload.quantity}, available {mat.available_quantity}."
            ),
        )

    remaining = payload.quantity
    lots_query = db.query(InventoryLot).filter(
        InventoryLot.material_id == mat.material_id,
        InventoryLot.available_quantity > 0,
    )
    if payload.lot_id is not None:
        lots_query = lots_query.filter(InventoryLot.lot_id == payload.lot_id)
    lots = lots_query.order_by(InventoryLot.availability_date).all()

    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot.available_quantity, remaining)
        lot.available_quantity = round(lot.available_quantity - take, 4)
        lot.reserved_quantity = round(lot.reserved_quantity + take, 4)
        remaining = round(remaining - take, 4)

    if remaining > 1e-6:
        raise HTTPException(status_code=400, detail="Insufficient lot stock to complete reservation.")

    recalculate_material_totals(db, mat)
    record_audit_log(
        db,
        username=username,
        action="RESERVE_INVENTORY",
        entity_type="Material",
        entity_id=mat.material_id,
        new_value={"reserved_delta": payload.quantity},
        reason=payload.reason,
    )
    db.commit()
    db.refresh(mat)
    return mat


def consume_inventory(
    db: Session, payload: InventoryActionRequest, username: str = "system"
) -> Material:
    """Consume reserved or available stock while strictly blocking negative inventory."""
    mat = db.query(Material).filter(Material.material_id == payload.material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail=f"Material '{payload.material_id}' not found.")

    total_usable = round(mat.reserved_quantity + mat.available_quantity, 4)
    if total_usable < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Negative inventory blocked for '{mat.material_id}': "
                f"cannot consume {payload.quantity} with only {total_usable} usable."
            ),
        )

    remaining = payload.quantity
    lots = (
        db.query(InventoryLot)
        .filter(InventoryLot.material_id == mat.material_id)
        .order_by(InventoryLot.availability_date)
        .all()
    )
    for lot in lots:
        if remaining <= 0:
            break
        if lot.reserved_quantity > 0:
            take_res = min(lot.reserved_quantity, remaining)
            lot.reserved_quantity = round(lot.reserved_quantity - take_res, 4)
            lot.consumed_quantity = round(lot.consumed_quantity + take_res, 4)
            remaining = round(remaining - take_res, 4)
        if remaining > 0 and lot.available_quantity > 0:
            take_avail = min(lot.available_quantity, remaining)
            lot.available_quantity = round(lot.available_quantity - take_avail, 4)
            lot.consumed_quantity = round(lot.consumed_quantity + take_avail, 4)
            remaining = round(remaining - take_avail, 4)
        if lot.available_quantity == 0 and lot.reserved_quantity == 0:
            lot.status = "Depleted"

    recalculate_material_totals(db, mat)
    record_audit_log(
        db,
        username=username,
        action="CONSUME_INVENTORY",
        entity_type="Material",
        entity_id=mat.material_id,
        new_value={"consumed_delta": payload.quantity},
        reason=payload.reason,
    )
    db.commit()
    db.refresh(mat)
    return mat


def detect_material_shortages(db: Session, reference_date: date | None = None) -> dict:
    """Compare active order demand against available inventory and flag shortages/delays."""
    active_orders = (
        db.query(ProductionOrder)
        .filter(
            ProductionOrder.status.in_(
                [
                    OrderStatus.RELEASED.value,
                    OrderStatus.PLANNED.value,
                    OrderStatus.SCHEDULED.value,
                    OrderStatus.IN_PROGRESS.value,
                ]
            )
        )
        .all()
    )
    demand_by_mat: dict[str, float] = {}
    for order in active_orders:
        boms = (
            db.query(MaterialRequirement)
            .filter(MaterialRequirement.product_id == order.product_id)
            .all()
        )
        for bom in boms:
            needed = order.quantity * bom.quantity_per_unit * (1.0 + bom.scrap_factor)
            demand_by_mat[bom.material_id] = round(
                demand_by_mat.get(bom.material_id, 0.0) + needed, 2
            )

    shortages = []
    delayed_lots = db.query(InventoryLot).filter(InventoryLot.is_delayed == True).all()  # noqa: E712
    for mat in db.query(Material).all():
        required = demand_by_mat.get(mat.material_id, 0.0)
        on_hand = mat.available_quantity + mat.reserved_quantity
        if required > on_hand or mat.stock_status in (
            StockStatus.LOW_STOCK.value,
            StockStatus.OUT_OF_STOCK.value,
        ):
            shortages.append(
                {
                    "material_id": mat.material_id,
                    "name": mat.name,
                    "stock_status": mat.stock_status,
                    "on_hand_quantity": round(on_hand, 2),
                    "required_by_active_orders": required,
                    "deficit": round(max(0.0, required - on_hand), 2),
                }
            )

    return {
        "shortage_count": len(shortages),
        "delayed_lot_count": len(delayed_lots),
        "shortages": shortages,
        "delayed_lots": [
            {
                "lot_number": l.lot_number,
                "material_id": l.material_id,
                "quantity": l.available_quantity,
                "availability_date": str(l.availability_date),
            }
            for l in delayed_lots
        ],
    }

