"""
Phase 7 Automated Tests: Verify all 5 mandatory negative anomaly detections,
extended detections, exception resolution history, and strict ground-truth separation.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import PROJECT_ROOT
from app.database.base import Base
import app.models  # noqa: F401
from app.generators.generate_data import (
    DEFAULT_SEED,
    export_dataset,
    generate_anomaly_scenarios_and_ground_truth,
    generate_dataset,
    load_dataset_to_db,
)
from app.models import InventoryLot, MachineDowntime, OperationSchedule, ProductionOrder
from app.routers import exceptions as exceptions_router
from app.routers.exceptions import ResolveExceptionRequest
from app.validators.anomaly_detector import detect_schedule_anomalies
from app.validators.ground_truth_evaluator import evaluate_against_ground_truth


@pytest.fixture()
def db() -> Session:
    test_engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    SessionLocalTest = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = SessionLocalTest()
    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    _, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)
    load_dataset_to_db(dataset, gt_rows, session)
    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()


def test_clean_baseline_has_zero_anomalies(db: Session) -> None:
    detected = detect_schedule_anomalies(db)
    assert detected == [], f"Unexpected baseline anomalies: {detected}"


def test_detects_all_5_mandatory_schedule_anomalies(db: Session) -> None:
    schedules = db.query(OperationSchedule).order_by(OperationSchedule.schedule_id).all()
    s1, s2 = schedules[0], schedules[1]

    # 1 & 2. Inject MachineOverlap + PrecedenceViolation + ChangeoverOmitted
    s2.machine_id = s1.machine_id
    s2.start_time = s1.start_time
    s2.end_time = s1.start_time + timedelta(minutes=30)
    s2.changeover_minutes = 0
    # Ensure s1 and s2 belong to different products if needed for ChangeoverOmitted
    orders = db.query(ProductionOrder).order_by(ProductionOrder.order_id).all()
    if len(orders) >= 2:
        orders[0].product_id = "PROD-2026-000001"
        orders[1].product_id = "PROD-2026-000002"
        s2.order_id = orders[1].order_id

    # 3. MaterialBeforeAvailability: push all lots for PROD-2026-000001's materials into future
    for lot in db.query(InventoryLot).all():
        lot.availability_date = date(2026, 12, 25)

    # 4. OutsideShiftCalendar: place s3 at 23:00
    s3 = schedules[2]
    s3.start_time = datetime(2026, 11, 16, 23, 0)
    s3.end_time = datetime(2026, 11, 16, 23, 30)

    # 5. MachineDowntimeConflict: place s4 inside downtime
    dt = db.query(MachineDowntime).first()
    s4 = schedules[3]
    s4.machine_id = dt.machine_id
    s4.start_time = dt.start_time
    s4.end_time = dt.start_time + timedelta(minutes=20)
    db.commit()

    detected = detect_schedule_anomalies(db)
    found_types = {d["issue_type"] for d in detected}
    assert "MachineOverlap" in found_types
    assert "PrecedenceViolation" in found_types
    assert "MaterialBeforeAvailability" in found_types
    assert "OutsideShiftCalendar" in found_types
    assert "ChangeoverOmitted" in found_types
    assert "MachineDowntimeConflict" in found_types


def test_ground_truth_separation_and_evaluation(db: Session, tmp_path: Path) -> None:
    # Verify anomaly_detector does not reference GroundTruth model or ground_truth files
    detector_src = (
        PROJECT_ROOT / "backend" / "app" / "validators" / "anomaly_detector.py"
    ).read_text(encoding="utf-8")
    assert "GroundTruth" not in detector_src
    assert "ground_truth.csv" not in detector_src
    assert "ground_truth.json" not in detector_src

    ds = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    sc, gt = generate_anomaly_scenarios_and_ground_truth(ds)
    export_dataset(ds, sc, gt, scale="starter", seed=DEFAULT_SEED, output_root=tmp_path)

    eval_result = evaluate_against_ground_truth(
        db,
        gt_path=tmp_path / "ground_truth" / "ground_truth.json",
        scenarios_path=tmp_path / "generated" / "anomaly_scenarios.json",
    )
    assert eval_result["true_positives"] == len(sc)
    assert eval_result["false_negatives"] == 0
    assert eval_result["false_positives"] == 0
    assert eval_result["true_negatives"] == 4
    assert eval_result["precision"] == 1.0
    assert eval_result["recall"] == 1.0
    assert eval_result["f1_score"] == 1.0


def test_exception_detection_and_resolution_workflow(db: Session) -> None:
    schedules = db.query(OperationSchedule).order_by(OperationSchedule.schedule_id).all()
    schedules[0].start_time = datetime(2026, 11, 16, 22, 0)
    schedules[0].end_time = datetime(2026, 11, 16, 23, 0)
    db.commit()

    res = exceptions_router.run_anomaly_detection(db=db)
    assert res["newly_saved_count"] >= 1

    listed = exceptions_router.list_exceptions(db=db)
    assert listed["summary"]["total"] >= 1
    first_id = listed["items"][0].anomaly_id

    resolved = exceptions_router.resolve_exception(
        first_id,
        ResolveExceptionRequest(
            resolution_status="Resolved",
            resolution_reason="Rescheduled operation back into Day Shift.",
            resolved_by="engineer",
        ),
        db=db,
    )
    assert resolved.resolution_status == "Resolved"

    detail = exceptions_router.get_exception_detail(first_id, db=db)
    assert len(detail["history"]) == 1

