"""FastAPI router for Materials, Inventory Lots, Stock Transactions, and Shortages."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models import InventoryLot, Material
from app.models.enums import RoleName
from app.schemas.common import PaginatedResponse
from app.schemas.materials import (
    InventoryActionRequest,
    InventoryLotCreate,
    InventoryLotOut,
    MaterialCreate,
    MaterialOut,
    MaterialUpdate,
)
from app.services import inventory_service


router = APIRouter(prefix="/api", tags=["Materials & Inventory"])


@router.get("/materials", response_model=PaginatedResponse[MaterialOut])
def list_materials(
    search: str | None = None,
    stock_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=300),
    db: Session = Depends(get_db),
):
    query = db.query(Material)
    if search:
        like = f"%{search}%"
        query = query.filter((Material.material_id.ilike(like)) | (Material.name.ilike(like)))
    if stock_status:
        query = query.filter(Material.stock_status == stock_status)
    total = query.count()
    items = query.order_by(Material.material_id).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post(
    "/materials",
    response_model=MaterialOut,
    status_code=201,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)):
    return inventory_service.create_material(db, payload)


@router.put(
    "/materials/{material_id}",
    response_model=MaterialOut,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def update_material(material_id: str, payload: MaterialUpdate, db: Session = Depends(get_db)):
    return inventory_service.update_material(db, material_id, payload)


@router.get("/inventory", response_model=list[InventoryLotOut])
def list_inventory_lots(
    material_id: str | None = None,
    delayed_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(InventoryLot)
    if material_id:
        query = query.filter(InventoryLot.material_id == material_id)
    if delayed_only:
        query = query.filter(InventoryLot.is_delayed == True)  # noqa: E712
    return query.order_by(InventoryLot.availability_date, InventoryLot.lot_id).limit(500).all()


@router.post(
    "/inventory/receive",
    response_model=InventoryLotOut,
    status_code=201,
    dependencies=[
        Depends(
            require_roles(
                RoleName.ADMIN.value,
                RoleName.PRODUCTION_PLANNER.value,
                RoleName.PLANT_OPERATOR.value,
            )
        )
    ],
)
def receive_inventory(payload: InventoryLotCreate, db: Session = Depends(get_db)):
    return inventory_service.receive_inventory_lot(db, payload)


@router.post(
    "/inventory/reserve",
    response_model=MaterialOut,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def reserve_inventory(payload: InventoryActionRequest, db: Session = Depends(get_db)):
    return inventory_service.reserve_inventory(db, payload)


@router.post(
    "/inventory/consume",
    response_model=MaterialOut,
    dependencies=[
        Depends(
            require_roles(
                RoleName.ADMIN.value,
                RoleName.PRODUCTION_PLANNER.value,
                RoleName.PLANT_OPERATOR.value,
            )
        )
    ],
)
def consume_inventory(payload: InventoryActionRequest, db: Session = Depends(get_db)):
    return inventory_service.consume_inventory(db, payload)


@router.get("/inventory/shortages")
def get_material_shortages(db: Session = Depends(get_db)):
    return inventory_service.detect_material_shortages(db)
