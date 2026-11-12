"""
FastAPI router for Audit Logs, State Change Events, Notifications,
Global Search, and Runtime System Settings.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_roles
from app.database.connection import get_db
from app.models import (
    AuditLog,
    Machine,
    Material,
    Notification,
    Product,
    ProductionOrder,
    StateChangeEvent,
)
from app.models.enums import RoleName
from app.services.audit_service import record_audit_log


router = APIRouter(prefix="/api", tags=["Audit, Search & Settings"])

# Mutable runtime settings initialized from environment defaults
_RUNTIME_SETTINGS = {
    "default_solver_time_limit_seconds": settings.DEFAULT_SOLVER_TIME_LIMIT_SECONDS,
    "default_weight_makespan": 1.0,
    "default_weight_lateness": 3.0,
    "default_weight_changeover": 1.5,
    "plant_name": "PlantOps Precision Manufacturing Facility",
    "default_shift_hours": "08:00 - 16:00 (30m break)",
}


class SettingsUpdate(BaseModel):
    default_solver_time_limit_seconds: int = Field(30, ge=1, le=300)
    default_weight_makespan: float = Field(1.0, ge=0.0)
    default_weight_lateness: float = Field(3.0, ge=0.0)
    default_weight_changeover: float = Field(1.5, ge=0.0)
    plant_name: str = Field(..., min_length=2, max_length=150)
    default_shift_hours: str = Field(..., min_length=3, max_length=100)


@router.get("/audit-logs")
def list_audit_logs(
    username: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id.ilike(f"%{entity_id}%"))
    return query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()


@router.get("/state-changes")
def list_state_changes(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(StateChangeEvent)
    if entity_type:
        query = query.filter(StateChangeEvent.entity_type == entity_type)
    if entity_id:
        query = query.filter(StateChangeEvent.entity_id == entity_id)
    return query.order_by(StateChangeEvent.created_at.desc(), StateChangeEvent.id.desc()).limit(limit).all()


@router.get("/notifications")
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db)):
    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712
    items = query.order_by(Notification.created_at.desc()).limit(50).all()
    unread_count = db.query(Notification).filter(Notification.is_read == False).count()  # noqa: E712
    return {"unread_count": unread_count, "items": items}


@router.patch("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notif.is_read = True
    db.commit()
    return {"id": notif.id, "is_read": True}


@router.get("/search")
def global_search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    like = f"%{q}%"
    orders = (
        db.query(ProductionOrder)
        .filter((ProductionOrder.order_id.ilike(like)) | (ProductionOrder.customer_name.ilike(like)))
        .limit(5)
        .all()
    )
    products = (
        db.query(Product)
        .filter((Product.product_id.ilike(like)) | (Product.sku.ilike(like)) | (Product.name.ilike(like)))
        .limit(5)
        .all()
    )
    machines = (
        db.query(Machine)
        .filter((Machine.machine_id.ilike(like)) | (Machine.name.ilike(like)))
        .limit(5)
        .all()
    )
    materials = (
        db.query(Material)
        .filter((Material.material_id.ilike(like)) | (Material.name.ilike(like)))
        .limit(5)
        .all()
    )
    return {
        "query": q,
        "orders": [{"id": o.order_id, "label": f"{o.order_id} ({o.status})"} for o in orders],
        "products": [{"id": p.product_id, "label": f"{p.sku} - {p.name}"} for p in products],
        "machines": [{"id": m.machine_id, "label": f"{m.machine_id} - {m.name}"} for m in machines],
        "materials": [{"id": m.material_id, "label": f"{m.material_id} - {m.name}"} for m in materials],
    }


@router.get("/settings")
def get_system_settings():
    return _RUNTIME_SETTINGS


@router.put("/settings", dependencies=[Depends(require_roles(RoleName.ADMIN.value))])
def update_system_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    old = dict(_RUNTIME_SETTINGS)
    _RUNTIME_SETTINGS.update(payload.model_dump())
    record_audit_log(
        db,
        username="admin",
        action="UPDATE_SETTINGS",
        entity_type="SystemSettings",
        entity_id="GLOBAL",
        old_value=old,
        new_value=_RUNTIME_SETTINGS,
    )
    db.commit()
    return _RUNTIME_SETTINGS

