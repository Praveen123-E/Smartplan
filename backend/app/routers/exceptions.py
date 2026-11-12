"""FastAPI router for Exceptions / Anomalies and Isolated Ground Truth Evaluation."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models import ConstraintViolation, StateChangeEvent
from app.models.enums import ResolutionStatus, RoleName
from app.services.audit_service import record_audit_log, record_state_change
from app.validators.anomaly_detector import (
    detect_schedule_anomalies,
    evaluate_isolated_scenarios,
    persist_detected_anomalies,
)
from app.validators.ground_truth_evaluator import evaluate_against_ground_truth


router = APIRouter(prefix="/api", tags=["Exceptions & Ground Truth"])


class ExceptionOut(BaseModel):
    anomaly_id: str
    run_id: str | None = None
    issue_type: str
    entity_type: str
    entity_id: str
    severity: str
    expected_result: str
    actual_result: str
    detection_status: str
    explanation: str
    suggested_action: str | None = None
    resolution_status: str
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResolveExceptionRequest(BaseModel):
    resolution_status: str = ResolutionStatus.RESOLVED.value
    resolution_reason: str = Field(..., min_length=3, max_length=1000)
    resolved_by: str = "engineer"


@router.get("/exceptions")
def list_exceptions(
    issue_type: str | None = None,
    severity: str | None = None,
    resolution_status: str | None = None,
    entity_id: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(ConstraintViolation)
    if issue_type:
        query = query.filter(ConstraintViolation.issue_type == issue_type)
    if severity:
        query = query.filter(ConstraintViolation.severity == severity)
    if resolution_status:
        query = query.filter(ConstraintViolation.resolution_status == resolution_status)
    if entity_id:
        query = query.filter(ConstraintViolation.entity_id.ilike(f"%{entity_id}%"))
    if run_id:
        query = query.filter(ConstraintViolation.run_id == run_id)

    items = query.order_by(ConstraintViolation.created_at.desc()).all()
    all_rows = db.query(ConstraintViolation).all()
    summary = {
        "total": len(all_rows),
        "critical": sum(1 for r in all_rows if r.severity == "Critical"),
        "warning": sum(1 for r in all_rows if r.severity == "Warning"),
        "pending": sum(1 for r in all_rows if r.resolution_status in ("Open", "In Review")),
        "resolved": sum(1 for r in all_rows if r.resolution_status == "Resolved"),
    }
    return {
        "summary": summary,
        "items": [ExceptionOut.model_validate(x) for x in items],
    }


@router.post("/exceptions/detect")
def run_anomaly_detection(
    run_id: str | None = None,
    include_negative_scenarios: bool = False,
    db: Session = Depends(get_db),
):
    detected = detect_schedule_anomalies(db, run_id=run_id)
    if include_negative_scenarios:
        detected.extend(evaluate_isolated_scenarios(db))
    saved = persist_detected_anomalies(db, detected)
    return {
        "detected_count": len(detected),
        "newly_saved_count": len(saved),
        "items": [ExceptionOut.model_validate(s) for s in saved],
    }


@router.get("/exceptions/{anomaly_id}")
def get_exception_detail(anomaly_id: str, db: Session = Depends(get_db)):
    item = (
        db.query(ConstraintViolation)
        .filter(ConstraintViolation.anomaly_id == anomaly_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail=f"Exception '{anomaly_id}' not found.")

    history = (
        db.query(StateChangeEvent)
        .filter(
            StateChangeEvent.entity_type == "ConstraintViolation",
            StateChangeEvent.entity_id == anomaly_id,
        )
        .order_by(StateChangeEvent.created_at.asc())
        .all()
    )
    return {
        "exception": ExceptionOut.model_validate(item),
        "history": [
            {
                "previous_state": h.previous_state,
                "new_state": h.new_state,
                "changed_by": h.changed_by,
                "reason": h.reason,
                "created_at": h.created_at,
            }
            for h in history
        ],
    }


@router.put(
    "/exceptions/{anomaly_id}/resolve",
    response_model=ExceptionOut,
    dependencies=[
        Depends(
            require_roles(
                RoleName.ADMIN.value,
                RoleName.MAINTENANCE_QUALITY_ENGINEER.value,
                RoleName.PRODUCTION_PLANNER.value,
            )
        )
    ],
)
def resolve_exception(
    anomaly_id: str,
    payload: ResolveExceptionRequest,
    db: Session = Depends(get_db),
):
    item = (
        db.query(ConstraintViolation)
        .filter(ConstraintViolation.anomaly_id == anomaly_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail=f"Exception '{anomaly_id}' not found.")
    if payload.resolution_status not in {e.value for e in ResolutionStatus}:
        raise HTTPException(status_code=400, detail="Invalid resolution_status.")

    prev = item.resolution_status
    item.resolution_status = payload.resolution_status
    item.resolved_by = payload.resolved_by
    item.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    item.resolution_reason = payload.resolution_reason

    record_state_change(
        db,
        entity_type="ConstraintViolation",
        entity_id=anomaly_id,
        previous_state=prev,
        new_state=payload.resolution_status,
        changed_by=payload.resolved_by,
        reason=payload.resolution_reason,
    )
    record_audit_log(
        db,
        username=payload.resolved_by,
        action="RESOLVE_EXCEPTION",
        entity_type="ConstraintViolation",
        entity_id=anomaly_id,
        old_value=prev,
        new_value=payload.resolution_status,
        reason=payload.resolution_reason,
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/ground-truth/evaluation")
def get_ground_truth_evaluation(db: Session = Depends(get_db)):
    return evaluate_against_ground_truth(db)
