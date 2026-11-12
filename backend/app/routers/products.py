"""FastAPI router for Products, Routings, Operations, and BOM Material Requirements."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models import Operation, Routing
from app.models.enums import RoleName
from app.schemas.common import PaginatedResponse
from app.schemas.products import (
    MaterialRequirementCreate,
    OperationOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    RoutingCreate,
    RoutingOut,
)
from app.services import product_service


router = APIRouter(prefix="/api", tags=["Products & Routings"])


@router.get("/products", response_model=PaginatedResponse[ProductOut])
def get_products(
    search: str | None = None,
    category: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    total, items = product_service.list_products(db, search, category, status, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=201,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    return product_service.create_product(db, payload)


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    detail = product_service.get_product_detail(db, product_id)
    return {
        "product": ProductOut.model_validate(detail["product"]),
        "routings": detail["routings"],
        "material_requirements": detail["material_requirements"],
    }


@router.put(
    "/products/{product_id}",
    response_model=ProductOut,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def update_product(product_id: str, payload: ProductUpdate, db: Session = Depends(get_db)):
    return product_service.update_product(db, product_id, payload)


@router.get("/routings", response_model=list[RoutingOut])
def list_routings(product_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Routing)
    if product_id:
        query = query.filter(Routing.product_id == product_id)
    routings = query.order_by(Routing.routing_id).all()
    return [product_service.build_routing_detail(db, r) for r in routings]


@router.post(
    "/routings",
    response_model=RoutingOut,
    status_code=201,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def create_routing(payload: RoutingCreate, db: Session = Depends(get_db)):
    return product_service.create_routing(db, payload)


@router.get("/operations", response_model=list[OperationOut])
def list_master_operations(db: Session = Depends(get_db)):
    return db.query(Operation).order_by(Operation.operation_code).all()


@router.post("/material-requirements", status_code=201)
def add_bom_requirement(payload: MaterialRequirementCreate, db: Session = Depends(get_db)):
    mr = product_service.add_material_requirement(db, payload)
    return {
        "id": mr.id,
        "product_id": mr.product_id,
        "operation_code": mr.operation_code,
        "material_id": mr.material_id,
        "quantity_per_unit": mr.quantity_per_unit,
        "scrap_factor": mr.scrap_factor,
    }
