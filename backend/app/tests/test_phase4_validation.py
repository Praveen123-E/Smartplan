"""
Phase 4 Automated Tests: Verify the 14-point Data Validation Engine passes
on clean generated data and detects all deliberate integrity violations.
"""

from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
import app.models  # noqa: F401
from app.generators.generate_data import (
    DEFAULT_SEED,
    generate_anomaly_scenarios_and_ground_truth,
    generate_dataset,
    load_dataset_to_db,
)
from app.models import (
    MachineCalendar,
    Material,
    OperationSchedule,
    Product,
    ProductionOrder,
    ProductionOrderOperation,
    StateChangeEvent,
)
from app.utils.lifecycle import is_valid_order_transition
from app.validators.data_validator import run_validation


@pytest.fixture()
def seeded_db() -> Session:
    """Provide an isolated SQLite DB loaded with the valid starter dataset."""
    test_engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()

    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    _, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)
    load_dataset_to_db(dataset, gt_rows, session)

    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()


def test_clean_dataset_passes_all_14_checks(seeded_db: Session) -> None:
    """Baseline dataset must pass all 14 validation checks with zero issues."""
    report = run_validation(seeded_db)
    assert report["overall_status"] == "PASSED", f"Unexpected issues: {report['issues']}"
    assert report["passed_checks"] == 14
    assert report["total_issues"] == 0


def test_detects_invalid_business_id(seeded_db: Session) -> None:
    seeded_db.add(
        Product(
            product_id="BAD-ID-99",
            sku="SKU-BAD-99",
            name="Bad ID Product",
            category="Test",
        )
    )
    seeded_db.commit()
    report = run_validation(seeded_db)
    checks_failed = {i["check"] for i in report["issues"]}
    assert "valid_ids" in checks_failed


def test_detects_invalid_enum_and_negative_quantity(seeded_db: Session) -> None:
    order = seeded_db.query(ProductionOrder).first()
    order.status = "InvalidStatus"
    order.quantity = -5
    seeded_db.commit()

    report = run_validation(seeded_db)
    checks_failed = {i["check"] for i in report["issues"]}
    assert "allowed_enums" in checks_failed
    assert "positive_quantities" in checks_failed


def test_detects_bad_date_ordering(seeded_db: Session) -> None:
    order = seeded_db.query(ProductionOrder).first()
    order.due_date = order.release_date - timedelta(hours=2)
    seeded_db.commit()

    report = run_validation(seeded_db)
    assert any(i["check"] == "date_ordering" for i in report["issues"])


def test_detects_operation_sequence_gap(seeded_db: Session) -> None:
    op = (
        seeded_db.query(ProductionOrderOperation)
        .filter(ProductionOrderOperation.sequence_number == 2)
        .first()
    )
    op.sequence_number = 9
    seeded_db.commit()

    report = run_validation(seeded_db)
    assert any(i["check"] == "operation_sequence" for i in report["issues"])


def test_detects_negative_inventory_balance(seeded_db: Session) -> None:
    mat = seeded_db.query(Material).first()
    mat.available_quantity = -10.0
    seeded_db.commit()

    report = run_validation(seeded_db)
    assert any(i["check"] == "inventory_balances" for i in report["issues"])


def test_detects_invalid_calendar_holiday_working(seeded_db: Session) -> None:
    cal = seeded_db.query(MachineCalendar).first()
    cal.is_holiday = True
    cal.is_working_day = True
    seeded_db.commit()

    report = run_validation(seeded_db)
    assert any(i["check"] == "machine_calendars" for i in report["issues"])


def test_detects_invalid_lifecycle_transition(seeded_db: Session) -> None:
    assert is_valid_order_transition("Draft", "Released") is True
    assert is_valid_order_transition("Completed", "Draft") is False

    seeded_db.add(
        StateChangeEvent(
            entity_type="ProductionOrder",
            entity_id="ORD-2026-000001",
            previous_state="Completed",
            new_state="Draft",
            changed_by="tester",
            reason="Illegal revert",
        )
    )
    seeded_db.commit()
    report = run_validation(seeded_db)
    assert any(i["check"] == "lifecycle_transitions" for i in report["issues"])


def test_detects_derived_calculation_and_schedule_overlap(seeded_db: Session) -> None:
    schedules = seeded_db.query(OperationSchedule).order_by(OperationSchedule.schedule_id).all()
    s1, s2 = schedules[0], schedules[1]
    # Force s2 onto s1's machine and time window AND mismatch its duration
    s2.machine_id = s1.machine_id
    s2.start_time = s1.start_time
    s2.end_time = s1.end_time
    s2.duration_minutes = s2.duration_minutes + 25
    seeded_db.commit()

    report = run_validation(seeded_db)
    checks_failed = {i["check"] for i in report["issues"]}
    assert "derived_calculations" in checks_failed
    assert "schedule_consistency" in checks_failed

