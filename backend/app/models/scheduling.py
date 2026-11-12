"""
Scheduling ORM models: SchedulingRun, OperationSchedule, and ToolingAllocation.

Every solver run is stored as an independent `SchedulingRun` so historical
schedules are never silently overwritten and runs can be compared side by side.
"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import SolverStatus


class SchedulingRun(Base, TimestampMixin):
    """Metadata and KPI summary for a single OR-Tools scheduling execution."""

    __tablename__ = "scheduling_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_name: Mapped[str] = mapped_column(String(120), nullable=False)
    solver_status: Mapped[str] = mapped_column(
        String(30), default=SolverStatus.UNKNOWN.value, index=True, nullable=False
    )
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    makespan_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_lateness_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_changeover_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delayed_order_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unscheduled_operation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    on_time_delivery_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_machine_utilization_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Configurable solver weights & time limit
    weight_makespan: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    weight_lateness: Mapped[float] = mapped_column(Float, default=3.0, nullable=False)
    weight_changeover: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    solver_time_limit_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    infeasibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    operation_schedules: Mapped[list["OperationSchedule"]] = relationship(
        "OperationSchedule", back_populates="scheduling_run", cascade="all, delete-orphan"
    )


class OperationSchedule(Base, TimestampMixin):
    """Scheduled assignment of an order operation onto a machine (SCH-2026-000001)."""

    __tablename__ = "operation_schedules"

    schedule_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("scheduling_runs.run_id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("production_orders.order_id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_operation_id: Mapped[str] = mapped_column(
        String(48),
        ForeignKey("production_order_operations.operation_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    machine_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("machines.machine_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    labor_shift_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("labor_shifts.shift_id", ondelete="SET NULL"), nullable=True
    )
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    changeover_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changeover_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lateness_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Scheduled", nullable=False)

    # Relationships
    scheduling_run: Mapped["SchedulingRun"] = relationship(
        "SchedulingRun", back_populates="operation_schedules"
    )
    order_operation: Mapped["ProductionOrderOperation"] = relationship(
        "ProductionOrderOperation", back_populates="schedules"
    )
    tooling_allocations: Mapped[list["ToolingAllocation"]] = relationship(
        "ToolingAllocation", back_populates="schedule", cascade="all, delete-orphan"
    )


class ToolingAllocation(Base, TimestampMixin):
    """Tracks shared tooling reservations for scheduled operations."""

    __tablename__ = "tooling_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("operation_schedules.schedule_id", ondelete="CASCADE"), index=True, nullable=False
    )
    tooling_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("shared_tooling.tooling_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    allocated_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    schedule: Mapped["OperationSchedule"] = relationship(
        "OperationSchedule", back_populates="tooling_allocations"
    )

