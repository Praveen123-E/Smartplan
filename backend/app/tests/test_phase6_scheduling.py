"""
Phase 6 Automated Tests: Verify scheduling preprocessor, constraint window
calculations, infeasibility pre-checks, Gantt/metrics/comparison endpoints,
and Google OR-Tools CP-SAT solver (when `ortools` is installed).
"""

from datetime import datetime, timedelta
import importlib.util
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
    InventoryLot,
    Machine,
    Material,
    OperationMachineEligibility,
    OperationSchedule,
    ProductionOrder,
    SchedulingRun,
)
from app.routers import scheduling as scheduling_router
from app.scheduling.preprocessor import build_scheduling_problem, lookup_changeover_minutes
from app.scheduling.solver import run_production_scheduling
from app.schemas.scheduling import SchedulingRunRequest
from app.validators.data_validator import run_validation


ORTOOLS_AVAILABLE = importlib.util.find_spec("ortools") is not None


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


def test_preprocessor_builds_valid_windows_and_changeovers(db: Session) -> None:
    problem = build_scheduling_problem(db, max_orders=5)
    assert len(problem.orders) == 5
    assert not problem.infeasibility_reasons
    assert len(problem.machine_working_windows) >= 7
    assert len(problem.machine_blackouts) >= 7

    # Changeover lookup: same product = 0, different product > 0
    p1 = problem.orders[0].product_id
    p2 = next((o.product_id for o in problem.orders if o.product_id != p1), p1)
    assert lookup_changeover_minutes(problem, "MACH-001", p1, p1) == 0
    if p1 != p2:
        assert lookup_changeover_minutes(problem, "MACH-001", p1, p2) > 0


def test_preprocessor_detects_insufficient_material_and_missing_machine(db: Session) -> None:
    # Deplete all inventory lots for all materials
    for lot in db.query(InventoryLot).all():
        lot.available_quantity = 0.0
        lot.reserved_quantity = 0.0
    for mat in db.query(Material).all():
        mat.available_quantity = 0.0
        mat.reserved_quantity = 0.0
    db.commit()

    problem = build_scheduling_problem(db, max_orders=2)
    assert any("Insufficient material" in msg for msg in problem.infeasibility_reasons)

    # Remove all machine eligibility for OP-STD-001
    db.query(OperationMachineEligibility).filter(
        OperationMachineEligibility.operation_code == "OP-STD-001"
    ).delete()
    db.commit()
    problem2 = build_scheduling_problem(db, max_orders=2)
    assert any("no eligible active machines" in msg for msg in problem2.infeasibility_reasons)


def test_gantt_metrics_and_compare_endpoints(db: Session) -> None:
    runs = scheduling_router.list_scheduling_runs(db=db)
    assert len(runs) >= 1
    base_run = runs[0]

    gantt = scheduling_router.get_run_gantt_data(base_run.run_id, db=db)
    assert gantt["run"].run_id == base_run.run_id
    assert len(gantt["tasks"]) > 0
    assert len(gantt["downtimes"]) > 0

    metrics = scheduling_router.get_run_metrics(base_run.run_id, db=db)
    assert metrics["scheduled_operations"] == len(gantt["tasks"])

    # Create a second run record to test run comparison endpoint
    second = SchedulingRun(
        run_id="RUN-2026-000002",
        run_name="Comparison Test Run",
        solver_status="Feasible",
        makespan_minutes=base_run.makespan_minutes + 30,
        total_lateness_minutes=base_run.total_lateness_minutes,
        total_changeover_minutes=base_run.total_changeover_minutes + 10,
        started_at=base_run.started_at + timedelta(minutes=5),
    )
    db.add(second)
    db.commit()

    comp = scheduling_router.compare_scheduling_runs(
        run_ids=f"{base_run.run_id},{second.run_id}", db=db
    )
    assert len(comp["runs"]) == 2
    assert comp["runs"][1]["makespan_delta"] == 30


@pytest.mark.skipif(
    not ORTOOLS_AVAILABLE,
    reason="ortools package not installed in current Python environment; run pip install ortools locally.",
)
def test_ortools_feasible_scheduling_respects_all_hard_constraints(db: Session) -> None:
    req = SchedulingRunRequest(
        run_name="CP-SAT Feasible Test",
        max_orders=5,
        solver_time_limit_seconds=15,
    )
    run = run_production_scheduling(db, req, triggered_by="pytest")
    assert run.solver_status in ("Optimal", "Feasible")
    assert run.unscheduled_operation_count == 0
    assert run.makespan_minutes > 0

    # Verify all hard constraints using the validation engine
    report = run_validation(db)
    assert report["overall_status"] == "PASSED", f"Constraint issues: {report['issues']}"


@pytest.mark.skipif(
    not ORTOOLS_AVAILABLE,
    reason="ortools package not installed in current Python environment; run pip install ortools locally.",
)
def test_ortools_infeasible_scheduling_explains_reason(db: Session) -> None:
    # Put all machines Down so no operation can be scheduled
    for m in db.query(Machine).all():
        m.status = "Down"
    db.commit()

    req = SchedulingRunRequest(run_name="CP-SAT Infeasible Test", max_orders=3)
    run = run_production_scheduling(db, req, triggered_by="pytest")
    assert run.solver_status == "Infeasible"
    assert run.infeasibility_reason is not None and len(run.infeasibility_reason) > 0

