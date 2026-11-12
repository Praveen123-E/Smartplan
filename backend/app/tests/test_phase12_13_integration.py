"""
Phases 12 & 13 Integration Tests:
Verify complete frontend assets (all 17 pages + CSS/JS), `/ui` StaticFiles mount,
RBAC guards on materials endpoints, and full end-to-end operational flow.
"""

from datetime import datetime, timedelta
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import PROJECT_ROOT
from app.core.security import require_roles
from app.database.base import Base
import app.models  # noqa: F401
from app.generators.generate_data import (
    DEFAULT_SEED,
    generate_anomaly_scenarios_and_ground_truth,
    generate_dataset,
    load_dataset_to_db,
)
from app.main import app
from app.models.enums import RoleName
from app.routers import audit as audit_router
from app.routers import dashboard as dashboard_router
from app.routers import exceptions as exceptions_router
from app.routers import materials as materials_router
from app.routers import orders as orders_router
from app.routers import scheduling as scheduling_router
from app.routers import validation as validation_router
from app.routers.exceptions import ResolveExceptionRequest
from app.schemas.materials import MaterialCreate
from app.schemas.orders import OrderCreate, OrderStatusUpdate


EXPECTED_17_PAGES = [
    "overview",
    "orders",
    "products",
    "routings",
    "machines",
    "calendars",
    "materials",
    "changeovers",
    "scheduler",
    "gantt",
    "utilization",
    "exceptions",
    "ground-truth",
    "reports",
    "audit-logs",
    "users",
    "settings",
]


@pytest.fixture()
def db() -> Session:
    test_engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_frontend_files_and_all_17_pages_exist():
    frontend_dir = PROJECT_ROOT / "frontend"
    assert (frontend_dir / "index.html").is_file()
    assert (frontend_dir / "css" / "styles.css").is_file()
    for js_file in ("api.js", "charts.js", "gantt.js", "pages.js", "app.js"):
        assert (frontend_dir / "js" / js_file).is_file(), f"Missing frontend/js/{js_file}"

    index_html = (frontend_dir / "index.html").read_text(encoding="utf-8")
    pages_js = (frontend_dir / "js" / "pages.js").read_text(encoding="utf-8")

    for page_slug in EXPECTED_17_PAGES:
        assert (frontend_dir / "pages" / f"{page_slug}.html").is_file(), f"Missing page {page_slug}.html"
        assert f'data-page="{page_slug}"' in index_html, f"Sidebar missing data-page={page_slug}"
        assert page_slug in pages_js, f"pages.js missing controller for {page_slug}"


def test_fastapi_mounts_ui_and_all_routers():
    route_paths = {getattr(r, "path", "") for r in app.routes}
    assert "/ui" in route_paths
    assert "/" in route_paths
    assert "/health" in route_paths
    assert "/api/auth/login" in route_paths
    assert "/api/dashboard/summary" in route_paths
    assert "/api/scheduling/run" in route_paths
    assert "/api/exceptions" in route_paths
    assert "/api/validation/run" in route_paths
    assert "/api/audit-logs" in route_paths


def test_materials_rbac_and_end_to_end_workflow(db: Session):
    # 1. Seed starter dataset cleanly
    dataset = generate_dataset(scale="starter", seed=DEFAULT_SEED)
    _, gt_rows = generate_anomaly_scenarios_and_ground_truth(dataset)
    load_dataset_to_db(dataset, gt_rows, db)

    # 2. Check RBAC dependency logic for materials endpoints
    planner_guard = require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value)
    assert planner_guard({"username": "planner", "roles": [RoleName.PRODUCTION_PLANNER.value]})
    with pytest.raises(HTTPException) as exc:
        planner_guard({"username": "operator", "roles": [RoleName.PLANT_OPERATOR.value]})
    assert exc.value.status_code == 403

    # 3. Create material & inspect list
    new_mat = materials_router.create_material(
        MaterialCreate(name="Titanium Bar 20mm", category="Metal", unit="kg", unit_cost=45.0, reorder_level=20.0),
        db=db,
    )
    assert new_mat.material_id.startswith("MAT-")

    # 4. Run 14-point validation report
    val_rep = validation_router.execute_validation(db=db)
    assert val_rep["overall_status"] == "PASSED"
    assert val_rep["passed_checks"] == 14

    # 5. Create an order, transition status, and fetch order details
    first_product = dataset["products"][0]["product_id"]
    now = datetime.now().replace(microsecond=0)
    created_ord = orders_router.create_order(
        OrderCreate(
            product_id=first_product,
            quantity=12,
            priority=2,
            customer_name="Integration Aero Corp",
            release_date=now,
            due_date=now + timedelta(days=3),
        ),
        db=db,
    )
    assert created_ord.status == "Draft"

    updated_ord = orders_router.update_order_status(
        created_ord.order_id,
        OrderStatusUpdate(new_status="Released", reason="Integration test release"),
        db=db,
    )
    assert updated_ord.status == "Released"

    # 6. Verify existing baseline scheduling run metrics & gantt payload
    runs = scheduling_router.list_scheduling_runs(db=db)
    assert len(runs) >= 1
    run_id = runs[0].run_id
    gantt = scheduling_router.get_run_gantt_data(run_id=run_id, db=db)
    assert "tasks" in gantt and "machines" in gantt
    metrics = scheduling_router.get_run_metrics(run_id=run_id, db=db)
    assert metrics["run_id"] == run_id

    # 7. Run anomaly detection + resolve one if present + verify dashboard & analytics export
    detect_res = exceptions_router.run_anomaly_detection(
        run_id=run_id,
        include_negative_scenarios=True,
        db=db,
    )
    assert detect_res["detected_count"] >= 1
    exc_list = exceptions_router.list_exceptions(db=db)
    if exc_list["items"]:
        first_anom = exc_list["items"][0].anomaly_id
        resolved = exceptions_router.resolve_exception(
            first_anom,
            ResolveExceptionRequest(
                resolution_status="Resolved",
                resolved_by="planner",
                resolution_reason="Integration test resolution",
            ),
            db=db,
        )
        assert resolved.resolution_status == "Resolved"

    # 8. Dashboard summary, charts, audit logs & CSV export
    summary = dashboard_router.get_dashboard_summary(db=db)
    assert summary["kpis"]["total_orders"] >= 1
    prod_charts = dashboard_router.get_production_charts(db=db)
    assert "order_status_chart" in prod_charts
    util_charts = dashboard_router.get_machine_utilization_charts(db=db)
    assert len(util_charts["machines"]) >= 1
    csv_resp = dashboard_router.export_analytics_csv(db=db)
    assert "run_id,run_name,solver_status" in csv_resp.body.decode("utf-8")
    audits = audit_router.list_audit_logs(limit=20, db=db)
    assert len(audits) >= 1
