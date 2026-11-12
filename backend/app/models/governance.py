"""
Governance, anomaly detection, ground truth, audit logging, state transitions,
and user notification ORM models.
"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, utc_now
from app.models.enums import ResolutionStatus, SeverityLevel


class ConstraintViolation(Base, TimestampMixin):
    """Detected scheduling or business-rule anomaly/exception record."""

    __tablename__ = "constraint_violations"

    anomaly_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("scheduling_runs.run_id", ondelete="SET NULL"), index=True, nullable=True
    )
    issue_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default=SeverityLevel.WARNING.value, index=True, nullable=False
    )
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    actual_result: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detection_status: Mapped[str] = mapped_column(String(30), default="Detected", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[str] = mapped_column(
        String(30), default=ResolutionStatus.OPEN.value, index=True, nullable=False
    )
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class GroundTruth(Base, TimestampMixin):
    """
    Isolated ground-truth labels for evaluation only.
    Never read by the scheduling engine or anomaly detector.
    """

    __tablename__ = "ground_truth"

    gt_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scenario_name: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    expected_is_anomaly: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_decision: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    """Immutable audit trail capturing user and system actions across the plant."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.user_id", ondelete="SET NULL"), index=True, nullable=True
    )
    username: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True, nullable=False)


class StateChangeEvent(Base):
    """Explicit lifecycle transition event (never silently overwrite business states)."""

    __tablename__ = "state_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_state: Mapped[str] = mapped_column(String(40), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True, nullable=False)


class Notification(Base):
    """In-app alert notification for planners, operators, and engineers."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.user_id", ondelete="CASCADE"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default=SeverityLevel.INFO.value, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True, nullable=False)

