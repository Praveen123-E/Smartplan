"""
Factory resource ORM models: Machine, MachineCalendar, MachineDowntime,
LaborShift, LaborResource, and SharedTooling.
"""

from datetime import date, datetime, time
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin
from app.models.enums import DowntimeType, MachineStatus


class Machine(Base, TimestampMixin):
    """Manufacturing machine / work-center asset (e.g., MACH-001)."""

    __tablename__ = "machines"

    machine_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    machine_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    work_center: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    capacity_per_hour: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    concurrent_job_capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    hourly_operating_cost: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=MachineStatus.AVAILABLE.value, index=True, nullable=False
    )

    # Relationships
    eligible_operations: Mapped[list["OperationMachineEligibility"]] = relationship(
        "OperationMachineEligibility", back_populates="machine", cascade="all, delete-orphan"
    )
    calendars: Mapped[list["MachineCalendar"]] = relationship(
        "MachineCalendar", back_populates="machine", cascade="all, delete-orphan"
    )
    downtimes: Mapped[list["MachineDowntime"]] = relationship(
        "MachineDowntime", back_populates="machine", cascade="all, delete-orphan"
    )


class MachineCalendar(Base, TimestampMixin):
    """Daily working calendar, shift window, breaks, and holiday flags for a machine."""

    __tablename__ = "machine_calendars"
    __table_args__ = (
        UniqueConstraint("machine_id", "calendar_date", "shift_name", name="uq_machine_date_shift"),
    )

    calendar_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("machines.machine_id", ondelete="CASCADE"), index=True, nullable=False
    )
    calendar_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    day_of_week: Mapped[str] = mapped_column(String(15), nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_holiday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shift_name: Mapped[str] = mapped_column(String(40), default="Day Shift", nullable=False)
    shift_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    shift_end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    available_minutes: Mapped[int] = mapped_column(Integer, default=450, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    machine: Mapped["Machine"] = relationship("Machine", back_populates="calendars")


class MachineDowntime(Base, TimestampMixin):
    """Planned maintenance windows and unplanned machine breakdown intervals."""

    __tablename__ = "machine_downtime"

    downtime_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("machines.machine_id", ondelete="CASCADE"), index=True, nullable=False
    )
    downtime_type: Mapped[str] = mapped_column(
        String(40), default=DowntimeType.PLANNED_MAINTENANCE.value, nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reported_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Scheduled", nullable=False)

    # Relationships
    machine: Mapped["Machine"] = relationship("Machine", back_populates="downtimes")


class LaborShift(Base, TimestampMixin):
    """Plant labor shift capacity for a given date and shift window."""

    __tablename__ = "labor_shifts"
    __table_args__ = (
        UniqueConstraint("shift_date", "shift_name", name="uq_labor_shift_date_name"),
    )

    shift_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shift_name: Mapped[str] = mapped_column(String(40), nullable=False)
    shift_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    total_headcount: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    available_headcount: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Active", nullable=False)

    # Relationships
    resources: Mapped[list["LaborResource"]] = relationship(
        "LaborResource", back_populates="shift", cascade="all, delete-orphan"
    )


class LaborResource(Base, TimestampMixin):
    """Individual operator/technician assigned to a labor shift."""

    __tablename__ = "labor_resources"

    labor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_group: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    shift_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labor_shifts.shift_id", ondelete="CASCADE"), index=True, nullable=False
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    shift: Mapped["LaborShift"] = relationship("LaborShift", back_populates="resources")


class SharedTooling(Base, TimestampMixin):
    """Shared fixtures, dies, or jigs with limited concurrent availability."""

    __tablename__ = "shared_tooling"

    tooling_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_type: Mapped[str] = mapped_column(String(60), nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="Available", nullable=False)

