"""
Phase 2 Automated Tests: Verify all 28 SQLAlchemy ORM models, primary keys,
foreign-key relationships, default role seeding, and schema creation.
"""

from datetime import date, datetime, time
import os
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.database.connection import check_database_connection
from app.database.init_db import seed_default_roles
import app.models  # noqa: F401 - register all 28 models
from app.models import (
    AuditLog,
    ChangeoverMatrix,
    ConstraintViolation,
    GroundTruth,
    InventoryLot,
    LaborResource,
    LaborShift,
    Machine,
    MachineCalendar,
    MachineDowntime,
    Material,
    MaterialRequirement,
    Notification,
    Operation,
    OperationMachineEligibility,
    OperationSchedule,
    Product,
    ProductionOrder,
    ProductionOrderOperation,
    Role,
    Routing,
    RoutingOperation,
    SchedulingRun,
    SharedTooling,
    StateChangeEvent,
    ToolingAllocation,
    User,
    UserRole,
)


EXPECTED_TABLES = {
    "products",
    "routings",
    "operations",
    "routing_operations",
    "operation_machine_eligibility",
    "machines",
    "machine_calendars",
    "machine_downtime",
    "labor_shifts",
    "labor_resources",
    "shared_tooling",
    "materials",
    "inventory_lots",
    "material_requirements",
    "production_orders",
    "production_order_operations",
    "changeover_matrix",
    "scheduling_runs",
    "operation_schedules",
    "tooling_allocations",
    "constraint_violations",
    "ground_truth",
    "audit_logs",
    "state_change_events",
    "notifications",
    "users",
    "roles",
    "user_roles",
}


@pytest.fixture()
def db_session() -> Session:
    """Create an isolated in-memory SQLite database with foreign keys enabled."""
    test_engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()


def test_all_28_tables_registered() -> None:
    """Confirm all 10 mandatory and 18 supporting tables exist in metadata."""
    registered_tables = set(Base.metadata.tables.keys())
    missing = EXPECTED_TABLES - registered_tables
    assert not missing, f"Missing SQLAlchemy tables: {missing}"
    assert len(registered_tables) == 28


def test_insert_complete_entity_graph(db_session: Session) -> None:
    """Insert linked records across all 28 tables to verify FKs and relationships."""
    seed_default_roles(db_session)
    assert db_session.query(Role).count() == 4

    # Idempotency check for seed_default_roles
    seed_default_roles(db_session)
    assert db_session.query(Role).count() == 4

    admin_role = db_session.query(Role).filter(Role.name == "Admin").first()
    user = User(
        user_id="USR-001",
        username="admin",
        email="admin@plantops.local",
        full_name="PlantOps Admin",
        hashed_password="hashed_secret_value",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.user_id, role_id=admin_role.role_id))

    tooling = SharedTooling(
        tooling_id="TOOL-001",
        name="CNC Fixture A",
        tool_type="Fixture",
        total_quantity=2,
        available_quantity=2,
    )
    product = Product(
        product_id="PROD-2026-000001",
        sku="SKU-0001",
        name="Precision Gear Shaft",
        category="Powertrain",
        unit_of_measure="pcs",
        standard_batch_size=50,
    )
    machine = Machine(
        machine_id="MACH-001",
        name="CNC Lathe 01",
        machine_type="CNC Lathe",
        work_center="WC-MACHINING",
        capacity_per_hour=12.0,
    )
    material = Material(
        material_id="MAT-2026-000001",
        name="Alloy Steel Bar 4140",
        category="Raw Metal",
        unit="kg",
        available_quantity=500.0,
    )
    db_session.add_all([tooling, product, machine, material])
    db_session.flush()

    routing = Routing(
        routing_id="ROUTE-SKU-0001-01",
        product_id=product.product_id,
        version="01",
        name="Standard Gear Shaft Routing",
        effective_from=date(2026, 1, 1),
    )
    operation = Operation(
        operation_code="OP-STD-001",
        name="Rough Turning",
        operation_type="Machining",
        tooling_id=tooling.tooling_id,
    )
    db_session.add_all([routing, operation])
    db_session.flush()

    routing_op = RoutingOperation(
        routing_id=routing.routing_id,
        operation_code=operation.operation_code,
        sequence_number=1,
        duration_per_unit_minutes=3.0,
        setup_minutes=15,
        labor_required=1,
        tooling_id=tooling.tooling_id,
    )
    eligibility = OperationMachineEligibility(
        operation_code=operation.operation_code,
        machine_id=machine.machine_id,
        efficiency_factor=1.0,
        is_preferred=True,
    )
    calendar = MachineCalendar(
        machine_id=machine.machine_id,
        calendar_date=date(2026, 11, 12),
        day_of_week="Thursday",
        shift_name="Day Shift",
        shift_start_time=time(8, 0),
        shift_end_time=time(16, 0),
        available_minutes=450,
    )
    downtime = MachineDowntime(
        machine_id=machine.machine_id,
        start_time=datetime(2026, 11, 12, 12, 0),
        end_time=datetime(2026, 11, 12, 12, 30),
        reason="Scheduled lubrication check",
    )
    shift = LaborShift(
        shift_name="Day Shift",
        shift_date=date(2026, 11, 12),
        start_time=time(8, 0),
        end_time=time(16, 0),
        total_headcount=10,
        available_headcount=10,
    )
    lot = InventoryLot(
        material_id=material.material_id,
        lot_number="LOT-2026-0001",
        initial_quantity=500.0,
        available_quantity=500.0,
        availability_date=date(2026, 11, 1),
    )
    mat_req = MaterialRequirement(
        product_id=product.product_id,
        operation_code=operation.operation_code,
        material_id=material.material_id,
        quantity_per_unit=2.5,
    )
    db_session.add_all([routing_op, eligibility, calendar, downtime, shift, lot, mat_req])
    db_session.flush()

    labor_res = LaborResource(
        employee_code="EMP-001",
        full_name="Ravi Kumar",
        skill_group="CNC Operator",
        shift_id=shift.shift_id,
    )
    order = ProductionOrder(
        order_id="ORD-2026-000001",
        product_id=product.product_id,
        routing_id=routing.routing_id,
        quantity=20,
        priority=1,
        release_date=datetime(2026, 11, 12, 8, 0),
        due_date=datetime(2026, 11, 13, 16, 0),
        status="Released",
    )
    changeover = ChangeoverMatrix(
        machine_id=machine.machine_id,
        from_product_id=product.product_id,
        to_product_id=product.product_id,
        changeover_minutes=0,
    )
    db_session.add_all([labor_res, order, changeover])
    db_session.flush()

    order_op = ProductionOrderOperation(
        operation_id="OP-ORD-2026-000001-01",
        order_id=order.order_id,
        routing_operation_id=routing_op.id,
        operation_code=operation.operation_code,
        sequence_number=1,
        planned_duration_minutes=60,
        setup_minutes=15,
        tooling_id=tooling.tooling_id,
    )
    run = SchedulingRun(
        run_id="RUN-2026-000001",
        run_name="Phase 2 Smoke Run",
        solver_status="Optimal",
        started_at=datetime(2026, 11, 12, 8, 0),
    )
    db_session.add_all([order_op, run])
    db_session.flush()

    schedule = OperationSchedule(
        schedule_id="SCH-2026-000001",
        run_id=run.run_id,
        order_id=order.order_id,
        order_operation_id=order_op.operation_id,
        machine_id=machine.machine_id,
        labor_shift_id=shift.shift_id,
        start_time=datetime(2026, 11, 12, 8, 0),
        end_time=datetime(2026, 11, 12, 9, 0),
        duration_minutes=60,
    )
    db_session.add(schedule)
    db_session.flush()

    alloc = ToolingAllocation(
        schedule_id=schedule.schedule_id,
        tooling_id=tooling.tooling_id,
        allocated_quantity=1,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
    )
    violation = ConstraintViolation(
        anomaly_id="ANOM-2026-000001",
        run_id=run.run_id,
        issue_type="SmokeCheck",
        entity_type="OperationSchedule",
        entity_id=schedule.schedule_id,
        severity="Info",
        expected_result="No overlap",
        actual_result="No overlap",
        explanation="Test anomaly row.",
    )
    gt = GroundTruth(
        gt_id="GT-001",
        scenario_name="baseline",
        issue_type="None",
        entity_type="OperationSchedule",
        entity_id=schedule.schedule_id,
        expected_is_anomaly=False,
        expected_decision="Feasible",
    )
    audit = AuditLog(
        user_id=user.user_id,
        username=user.username,
        action="CREATE",
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        new_value="Released",
    )
    state_evt = StateChangeEvent(
        entity_type="ProductionOrder",
        entity_id=order.order_id,
        previous_state="Draft",
        new_state="Released",
        changed_by=user.username,
        reason="Released by planner",
    )
    notif = Notification(
        user_id=user.user_id,
        title="Schedule Generated",
        message="Run RUN-2026-000001 completed.",
    )
    db_session.add_all([alloc, violation, gt, audit, state_evt, notif])
    db_session.commit()

    assert db_session.query(OperationSchedule).count() == 1
    assert len(product.routings) == 1
    assert len(order.operations) == 1


def test_primary_key_uniqueness_enforced(db_session: Session) -> None:
    """Inserting a duplicate primary key must raise IntegrityError."""
    db_session.add(
        Product(
            product_id="PROD-2026-000001",
            sku="SKU-DUP-1",
            name="Gear A",
            category="Mechanical",
        )
    )
    db_session.commit()

    db_session.add(
        Product(
            product_id="PROD-2026-000001",
            sku="SKU-DUP-2",
            name="Gear B",
            category="Mechanical",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_key_integrity_enforced(db_session: Session) -> None:
    """Inserting a child row with a missing parent FK must raise IntegrityError."""
    db_session.add(
        Routing(
            routing_id="ROUTE-BAD-01",
            product_id="PROD-DOES-NOT-EXIST",
            version="01",
            name="Invalid Routing",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.skipif(
    os.getenv("PLANTOPS_TEST_MYSQL") != "1",
    reason="Set PLANTOPS_TEST_MYSQL=1 with configured .env to run live MySQL check.",
)
def test_live_mysql_connection() -> None:
    """Verify live MySQL plantops_db connection when explicitly enabled."""
    assert check_database_connection() is True

