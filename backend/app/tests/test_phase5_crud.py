"""
Phase 5 Automated Tests: Verify FastAPI routes, CRUD services, inventory
negative-balance guards, order lifecycle transitions, utilization formula,
changeovers, and audit log recording.
"""

from datetime import date, datetime, time
from fastapi import HTTPException
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
from app.main import app
from app.models import AuditLog, StateChangeEvent
from app.routers import machines as machines_router
from app.routers import materials as materials_router
from app.routers import orders as orders_router
from app.routers import products as products_router
from app.routers import validation as validation_router
from app.schemas.machines import CalendarCreate, DowntimeCreate, MachineCreate
from app.schemas.materials import InventoryActionRequest, InventoryLotCreate, MaterialCreate
from app.schemas.orders import ChangeoverUpsert, OrderCreate, OrderStatusUpdate
from app.schemas.products import ProductCreate, RoutingCreate, RoutingStepIn


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


def test_phase5_routes_registered() -> None:
    paths = {route.path for route in app.routes}
    expected = {
        "/api/products",
        "/api/products/{product_id}",
        "/api/routings",
        "/api/machines",
        "/api/machines/{machine_id}",
        "/api/machines/{machine_id}/utilization",
        "/api/calendars",
        "/api/downtime",
        "/api/labor-shifts",
        "/api/materials",
        "/api/inventory",
        "/api/inventory/receive",
        "/api/inventory/reserve",
        "/api/inventory/consume",
        "/api/orders",
        "/api/orders/{order_id}",
        "/api/orders/{order_id}/status",
        "/api/changeovers",
        "/api/validation/run",
        "/api/validation/report",
    }
    assert expected.issubset(paths)


def test_product_and_routing_crud(db: Session) -> None:
    created = products_router.create_product(
        ProductCreate(
            sku="SKU-NEW-999",
            name="Hydraulic Valve Block",
            category="Hydraulic Assembly",
            standard_batch_size=25,
        ),
        db=db,
    )
    assert created.product_id.startswith("PROD-2026-")

    routing = products_router.create_routing(
        RoutingCreate(
            product_id=created.product_id,
            version="01",
            name="Valve Block Route",
            steps=[
                RoutingStepIn(operation_code="OP-STD-001", sequence_number=1, duration_per_unit_minutes=2.0),
                RoutingStepIn(operation_code="OP-STD-008", sequence_number=2, duration_per_unit_minutes=1.0),
            ],
        ),
        db=db,
    )
    assert routing["routing_id"] == "ROUTE-SKU-NEW-999-01"
    assert len(routing["steps"]) == 2


def test_machine_utilization_calendar_and_downtime(db: Session) -> None:
    mach = machines_router.create_machine(
        MachineCreate(name="CNC Mill Extra", machine_type="CNC Mill", work_center="WC-MACHINING"),
        db=db,
    )
    assert mach.machine_id == "MACH-009"

    cal = machines_router.create_calendar(
        CalendarCreate(
            machine_id=mach.machine_id,
            calendar_date=date(2026, 11, 20),
            shift_start_time=time(8, 0),
            shift_end_time=time(16, 0),
            break_start_time=time(12, 0),
            break_end_time=time(12, 30),
        ),
        db=db,
    )
    assert cal.available_minutes == 450

    dt = machines_router.create_downtime(
        DowntimeCreate(
            machine_id=mach.machine_id,
            start_time=datetime(2026, 11, 20, 10, 0),
            end_time=datetime(2026, 11, 20, 11, 0),
            reason="Calibration check",
        ),
        db=db,
    )
    assert dt.machine_id == mach.machine_id

    util = machines_router.get_machine_utilization("MACH-001", db=db)
    assert "utilization_pct" in util
    assert util["available_calendar_minutes"] > 0


def test_inventory_receive_reserve_consume_and_negative_guard(db: Session) -> None:
    mat = materials_router.create_material(
        MaterialCreate(name="Titanium Rod", category="Raw Metal", unit="kg", reorder_level=20.0),
        db=db,
    )
    materials_router.receive_inventory(
        InventoryLotCreate(
            material_id=mat.material_id,
            lot_number="LOT-TEST-001",
            quantity=100.0,
            availability_date=date(2026, 11, 15),
        ),
        db=db,
    )
    reserved = materials_router.reserve_inventory(
        InventoryActionRequest(material_id=mat.material_id, quantity=40.0), db=db
    )
    assert reserved.available_quantity == 60.0
    assert reserved.reserved_quantity == 40.0

    consumed = materials_router.consume_inventory(
        InventoryActionRequest(material_id=mat.material_id, quantity=50.0), db=db
    )
    assert consumed.consumed_quantity == 50.0
    assert consumed.available_quantity == 50.0

    # Negative inventory must be blocked
    with pytest.raises(HTTPException) as exc:
        materials_router.consume_inventory(
            InventoryActionRequest(material_id=mat.material_id, quantity=500.0), db=db
        )
    assert exc.value.status_code == 400


def test_order_creation_lifecycle_and_audit_history(db: Session) -> None:
    new_order = orders_router.create_order(
        OrderCreate(
            product_id="PROD-2026-000001",
            quantity=15,
            priority=1,
            customer_name="Acme Motors",
            release_date=datetime(2026, 11, 16, 8, 0),
            due_date=datetime(2026, 11, 18, 16, 0),
        ),
        db=db,
    )
    assert new_order.status == "Draft"
    assert new_order.is_urgent is True

    detail = orders_router.get_order(new_order.order_id, db=db)
    assert len(detail["operations"]) == 4

    # Valid transition Draft -> Released
    released = orders_router.update_order_status(
        new_order.order_id,
        OrderStatusUpdate(new_status="Released", reason="Approved by planner"),
        db=db,
    )
    assert released.status == "Released"

    # Invalid transition Released -> Completed (must go through Scheduled / In Progress)
    with pytest.raises(HTTPException) as exc:
        orders_router.update_order_status(
            new_order.order_id,
            OrderStatusUpdate(new_status="Completed", reason="Skip"),
            db=db,
        )
    assert exc.value.status_code == 400

    # Audit & state change history preserved
    events = db.query(StateChangeEvent).filter(StateChangeEvent.entity_id == new_order.order_id).all()
    assert len(events) == 2
    audits = db.query(AuditLog).filter(AuditLog.entity_id == new_order.order_id).all()
    assert len(audits) >= 2


def test_changeover_and_validation_endpoint(db: Session) -> None:
    co = orders_router.upsert_changeover(
        ChangeoverUpsert(
            machine_id="MACH-001",
            from_product_id="PROD-2026-000001",
            to_product_id="PROD-2026-000002",
            changeover_minutes=22,
            cleaning_required=True,
        ),
        db=db,
    )
    assert co.changeover_minutes == 22

    report = validation_router.execute_validation(db=db)
    assert report["overall_status"] == "PASSED"

