"""
Database initialization utility for PlantOps.

Creates all tables defined on `Base.metadata` (useful when setting up a fresh
database or testing environment) and seeds the 4 mandatory RBAC roles.
"""

from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.connection import SessionLocal, engine
from app.models.auth import Role
from app.models.enums import RoleName
import app.models  # noqa: F401 - register all models


DEFAULT_ROLES = [
    (RoleName.ADMIN.value, "OT/IT Administrator with full system configuration, user, and audit access."),
    (RoleName.PRODUCTION_PLANNER.value, "Creates orders, configures priorities, runs scheduling, and reviews analytics."),
    (RoleName.PLANT_OPERATOR.value, "Views assigned operations and machine schedules, updates progress, reports issues."),
    (RoleName.MAINTENANCE_QUALITY_ENGINEER.value, "Manages machine downtime, maintenance records, and resolves exceptions."),
]


def create_tables(target_engine=engine) -> None:
    """Create all 28 PlantOps tables on the given SQLAlchemy engine."""
    Base.metadata.create_all(bind=target_engine)


def seed_default_roles(db: Session) -> None:
    """Insert the 4 mandatory PlantOps roles if they do not already exist."""
    for role_name, description in DEFAULT_ROLES:
        existing = db.query(Role).filter(Role.name == role_name).first()
        if not existing:
            db.add(Role(name=role_name, description=description))
    db.commit()


if __name__ == "__main__":
    create_tables()
    with SessionLocal() as session:
        seed_default_roles(session)
    print("Database tables and default roles initialized successfully.")

