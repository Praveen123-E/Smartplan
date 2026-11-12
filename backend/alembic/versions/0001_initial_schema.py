"""Create initial PlantOps 28-table schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-12
"""

from alembic import op

from app.database.base import Base
import app.models  # noqa: F401 - register all 28 ORM models


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all 28 PlantOps tables in topological foreign-key order."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all PlantOps tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

