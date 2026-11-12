"""
Master data ORM models: Product, Routing, Operation, RoutingOperation,
and OperationMachineEligibility.
"""

from datetime import date
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import ProductStatus


class Product(Base, TimestampMixin):
    """Manufactured SKU / finished product (e.g., PROD-2026-000001)."""

    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    standard_batch_size: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default=ProductStatus.ACTIVE.value, index=True, nullable=False
    )

    # Relationships
    routings: Mapped[list["Routing"]] = relationship(
        "Routing", back_populates="product", cascade="all, delete-orphan"
    )
    material_requirements: Mapped[list["MaterialRequirement"]] = relationship(
        "MaterialRequirement", back_populates="product", cascade="all, delete-orphan"
    )
    production_orders: Mapped[list["ProductionOrder"]] = relationship(
        "ProductionOrder", back_populates="product"
    )


class Routing(Base, TimestampMixin):
    """Manufacturing process plan defining the sequence of operations for a product."""

    __tablename__ = "routings"

    routing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.product_id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(String(16), default="01", nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Active", nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="routings")
    routing_operations: Mapped[list["RoutingOperation"]] = relationship(
        "RoutingOperation",
        back_populates="routing",
        order_by="RoutingOperation.sequence_number",
        cascade="all, delete-orphan",
    )


class Operation(Base, TimestampMixin):
    """Master operation template (e.g., Cutting, CNC Milling, Assembly, Testing)."""

    __tablename__ = "operations"

    operation_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_setup_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    default_run_minutes_per_unit: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    required_labor_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tooling_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shared_tooling.tooling_id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="Active", nullable=False)

    # Relationships
    routing_operations: Mapped[list["RoutingOperation"]] = relationship(
        "RoutingOperation", back_populates="operation"
    )
    eligible_machines: Mapped[list["OperationMachineEligibility"]] = relationship(
        "OperationMachineEligibility", back_populates="operation", cascade="all, delete-orphan"
    )


class RoutingOperation(Base, TimestampMixin):
    """Ordered step inside a product routing (links Routing to Operation)."""

    __tablename__ = "routing_operations"
    __table_args__ = (
        UniqueConstraint("routing_id", "sequence_number", name="uq_routing_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routing_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("routings.routing_id", ondelete="CASCADE"), index=True, nullable=False
    )
    operation_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("operations.operation_code", ondelete="RESTRICT"), index=True, nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_per_unit_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    setup_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    labor_required: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tooling_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shared_tooling.tooling_id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    routing: Mapped["Routing"] = relationship("Routing", back_populates="routing_operations")
    operation: Mapped["Operation"] = relationship("Operation", back_populates="routing_operations")


class OperationMachineEligibility(Base, TimestampMixin):
    """Many-to-many bridge defining which machines can run each operation type."""

    __tablename__ = "operation_machine_eligibility"
    __table_args__ = (
        UniqueConstraint("operation_code", "machine_id", name="uq_operation_machine"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("operations.operation_code", ondelete="CASCADE"), index=True, nullable=False
    )
    machine_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("machines.machine_id", ondelete="CASCADE"), index=True, nullable=False
    )
    efficiency_factor: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    operation: Mapped["Operation"] = relationship("Operation", back_populates="eligible_machines")
    machine: Mapped["Machine"] = relationship("Machine", back_populates="eligible_operations")

