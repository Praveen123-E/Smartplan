"""FastAPI router for Production Orders, Order Operations, and Changeover Matrix."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models import ChangeoverMatrix
from app.models.enums import RoleName
from app.schemas.common import PaginatedResponse
from app.schemas.orders import (
    ChangeoverOut,
    ChangeoverUpsert,
    OrderCreate,
    OrderOperationOut,
    OrderOperationProgressUpdate,
    OrderOut,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services import order_service


router = APIRouter(prefix="/api", tags=["Orders & Changeovers"])


@router.get("/orders", response_model=PaginatedResponse[OrderOut])
def list_orders(
    search: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    sort_by: str = "order_id",
    sort_dir: str = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    total, items = order_service.list_orders(
        db, search, status, priority, sort_by, sort_dir, page, page_size
    )
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=201,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    return order_service.create_order(db, payload)


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    detail = order_service.get_order_detail(db, order_id)
    return {
        "order": OrderOut.model_validate(detail["order"]),
        "operations": [OrderOperationOut.model_validate(op) for op in detail["operations"]],
        "material_requirements": detail["material_requirements"],
    }


@router.put("/orders/{order_id}", response_model=OrderOut)
def update_order(order_id: str, payload: OrderUpdate, db: Session = Depends(get_db)):
    return order_service.update_order(db, order_id, payload)


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_order_status(order_id: str, payload: OrderStatusUpdate, db: Session = Depends(get_db)):
    return order_service.transition_order_status(db, order_id, payload)


@router.patch(
    "/operations/{operation_id}/progress",
    response_model=OrderOperationOut,
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
def update_operation_progress(
    operation_id: str, payload: OrderOperationProgressUpdate, db: Session = Depends(get_db)
):
    return order_service.update_operation_progress(db, operation_id, payload)


@router.get("/changeovers", response_model=list[ChangeoverOut])
def list_changeovers(
    machine_id: str | None = None,
    from_product_id: str | None = None,
    to_product_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(ChangeoverMatrix)
    if machine_id:
        query = query.filter(ChangeoverMatrix.machine_id == machine_id)
    if from_product_id:
        query = query.filter(ChangeoverMatrix.from_product_id == from_product_id)
    if to_product_id:
        query = query.filter(ChangeoverMatrix.to_product_id == to_product_id)
    return query.order_by(ChangeoverMatrix.id).limit(limit).all()


@router.post("/changeovers", response_model=ChangeoverOut, status_code=201)
def upsert_changeover(payload: ChangeoverUpsert, db: Session = Depends(get_db)):
    return order_service.upsert_changeover(db, payload)
