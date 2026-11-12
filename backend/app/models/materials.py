"""
Material and inventory ORM models: Material, InventoryLot, MaterialRequirement.
"""

from datetime import date
from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import StockStatus


class Material(Base, TimestampMixin):
    """Raw material or component SKU (e.g., MAT-2026-000001)."""

    __tablename__ = "materials"

    material_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="kg", nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    reorder_level: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    available_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reserved_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    consumed_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stock_status: Mapped[str] = mapped_column(
        String(30), default=StockStatus.IN_STOCK.value, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="Active", nullable=False)

    # Relationships
    inventory_lots: Mapped[list["InventoryLot"]] = relationship(
        "InventoryLot", back_populates="material", cascade="all, delete-orphan"
    )
    material_requirements: Mapped[list["MaterialRequirement"]] = relationship(
        "MaterialRequirement", back_populates="material"
    )


class InventoryLot(Base, TimestampMixin):
    """Batch/lot of a material with an explicit availability date."""

    __tablename__ = "inventory_lots"

    lot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("materials.material_id", ondelete="CASCADE"), index=True, nullable=False
    )
    lot_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    initial_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    available_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    reserved_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    consumed_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    availability_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_delayed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Available", nullable=False)

    # Relationships
    material: Mapped["Material"] = relationship("Material", back_populates="inventory_lots")


class MaterialRequirement(Base, TimestampMixin):
    """Bill-of-materials link defining how much material a product/operation consumes."""

    __tablename__ = "material_requirements"
    __table_args__ = (
        UniqueConstraint("product_id", "operation_code", "material_id", name="uq_bom_req"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.product_id", ondelete="CASCADE"), index=True, nullable=False
    )
    operation_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("operations.operation_code", ondelete="SET NULL"), nullable=True
    )
    material_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("materials.material_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    scrap_factor: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="material_requirements")
    material: Mapped["Material"] = relationship("Material", back_populates="material_requirements")

