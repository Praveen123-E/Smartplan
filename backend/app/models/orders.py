"""
Order and changeover ORM models: ProductionOrder, ProductionOrderOperation,
and ChangeoverMatrix.
"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import OperationExecutionStatus, OrderStatus


class ProductionOrder(Base, TimestampMixin):
    """Customer or internal manufacturing order (e.g., ORD-2026-000001)."""

    __tablename__ = "production_orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.product_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    routing_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("routings.routing_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, default=3, index=True, nullable=False, comment="1=Highest/Urgent, 5=Lowest"
    )
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    release_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=OrderStatus.DRAFT.value, index=True, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    product: Mapped["Product"] = relationship("Product", back_populates="production_orders")
    operations: Mapped[list["ProductionOrderOperation"]] = relationship(
        "ProductionOrderOperation",
        back_populates="order",
        order_by="ProductionOrderOperation.sequence_number",
        cascade="all, delete-orphan",
    )


class ProductionOrderOperation(Base, TimestampMixin):
    """Concrete operation step generated for a production order (OP-{order-id}-01)."""

    __tablename__ = "production_order_operations"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence_number", name="uq_order_op_seq"),
    )

    operation_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("production_orders.order_id", ondelete="CASCADE"), index=True, nullable=False
    )
    routing_operation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("routing_operations.id", ondelete="SET NULL"), nullable=True
    )
    operation_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("operations.operation_code", ondelete="RESTRICT"), index=True, nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    labor_required: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tooling_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("shared_tooling.tooling_id", ondelete="SET NULL"), nullable=True
    )
    completed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default=OperationExecutionStatus.PENDING.value, index=True, nullable=False
    )

    # Relationships
    order: Mapped["ProductionOrder"] = relationship("ProductionOrder", back_populates="operations")
    schedules: Mapped[list["OperationSchedule"]] = relationship(
        "OperationSchedule", back_populates="order_operation"
    )


class ChangeoverMatrix(Base, TimestampMixin):
    """Sequence-dependent setup time from `from_product_id` to `to_product_id`."""

    __tablename__ = "changeover_matrix"
    __table_args__ = (
        UniqueConstraint(
            "machine_id", "from_product_id", "to_product_id", name="uq_changeover_transition"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("machines.machine_id", ondelete="CASCADE"), index=True, nullable=True
    )
    from_product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.product_id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_product_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("products.product_id", ondelete="CASCADE"), index=True, nullable=False
    )
    changeover_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaning_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

