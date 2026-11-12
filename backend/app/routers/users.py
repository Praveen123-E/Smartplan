"""FastAPI router for Admin User & Role Management (RBAC-protected)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.security import get_user_roles, hash_password, require_roles
from app.database.connection import get_db
from app.models.auth import Role, User, UserRole
from app.models.enums import RoleName
from app.services.audit_service import record_audit_log
from app.utils.id_generator import next_numeric_suffix


router = APIRouter(
    prefix="/api/users",
    tags=["User Management"],
    dependencies=[Depends(require_roles(RoleName.ADMIN.value))],
)


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=6)
    role_name: str


class RoleUpdateRequest(BaseModel):
    role_name: str


@router.get("")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.user_id).all()
    return [
        {
            "user_id": u.user_id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "is_active": u.is_active,
            "last_login_at": u.last_login_at,
            "roles": get_user_roles(db, u.user_id),
        }
        for u in users
    ]


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).order_by(Role.role_id).all()


@router.post("", status_code=201)
def create_user_by_admin(payload: AdminUserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists.")
    role_obj = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role_obj:
        raise HTTPException(status_code=400, detail=f"Invalid role '{payload.role_name}'.")

    counter = next_numeric_suffix(db, User, User.user_id, "USR-")
    user = User(
        user_id=f"USR-{counter:03d}",
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.user_id, role_id=role_obj.role_id))
    record_audit_log(
        db,
        username="admin",
        action="ADMIN_CREATE_USER",
        entity_type="User",
        entity_id=user.user_id,
        new_value={"username": user.username, "role": role_obj.name},
    )
    db.commit()
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "roles": [role_obj.name],
    }


@router.put("/{user_id}/role")
def update_user_role(user_id: str, payload: RoleUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    role_obj = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role_obj:
        raise HTTPException(status_code=400, detail=f"Role '{payload.role_name}' not found.")

    old_roles = get_user_roles(db, user_id)
    db.query(UserRole).filter(UserRole.user_id == user_id).delete()
    db.add(UserRole(user_id=user_id, role_id=role_obj.role_id))
    record_audit_log(
        db,
        username="admin",
        action="UPDATE_USER_ROLE",
        entity_type="User",
        entity_id=user_id,
        old_value=old_roles,
        new_value=[role_obj.name],
    )
    db.commit()
    return {"user_id": user_id, "roles": [role_obj.name]}


@router.patch("/{user_id}/toggle-active")
def toggle_user_active(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    user.is_active = not user.is_active
    record_audit_log(
        db,
        username="admin",
        action="TOGGLE_USER_ACTIVE",
        entity_type="User",
        entity_id=user_id,
        new_value={"is_active": user.is_active},
    )
    db.commit()
    return {"user_id": user_id, "is_active": user.is_active}

