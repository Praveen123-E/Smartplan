"""FastAPI router for Authentication: Login, Register, and Current User Profile."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user,
    get_user_roles,
    hash_password,
    verify_password,
)
from app.database.connection import get_db
from app.models.auth import Role, User, UserRole
from app.models.enums import RoleName
from app.services.audit_service import record_audit_log
from app.utils.id_generator import next_numeric_suffix


router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2)
    password: str = Field(..., min_length=4)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=6)
    role_name: str = RoleName.PLANT_OPERATOR.value


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled.",
        )

    roles = get_user_roles(db, user.user_id)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit_log(
        db,
        username=user.username,
        action="USER_LOGIN",
        entity_type="User",
        entity_id=user.user_id,
        user_id=user.user_id,
    )
    db.commit()

    token = create_access_token(user.user_id, user.username, roles)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "roles": roles,
        },
    }


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists.")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already exists.")

    # Self-registration defaults to Plant Operator unless Admin provisions other roles
    role_obj = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role_obj:
        role_obj = db.query(Role).filter(Role.name == RoleName.PLANT_OPERATOR.value).first()
        if not role_obj:
            role_obj = Role(name=RoleName.PLANT_OPERATOR.value, description="Plant Operator")
            db.add(role_obj)
            db.flush()

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
        username=user.username,
        action="USER_REGISTER",
        entity_type="User",
        entity_id=user.user_id,
        new_value={"role": role_obj.name},
        user_id=user.user_id,
    )
    db.commit()
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "roles": [role_obj.name],
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

