"""
Phases 10 & 11 Automated Tests: Verify Dashboard KPIs, Chart.js datasets,
CSV Analytics export, Audit/Search/Settings APIs, JWT Auth, and Backend RBAC.
"""

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.database.base import Base
import app.models  # noqa: F401
from app.generators.generate_data import (
    DEFAULT_SEED,
    generate_anomaly_scenarios_and_ground_truth,
    generate_dataset,
    load_dataset_to_db,
)
from app.main import app
from app.routers import audit as audit_router
from app.routers import auth as auth_router
from app.routers import dashboard as dashboard_router
from app.routers import users as users_router
from app.routers.audit import SettingsUpdate
from app.routers.auth import LoginRequest, RegisterRequest
from app.routers.users import AdminUserCreate, RoleUpdateRequest


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


def test_all_api_routes_registered() -> None:
    paths = {r.path for r in app.routes}
    expected = {
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/me",
        "/api/users",
        "/api/dashboard/summary",
        "/api/dashboard/production",
        "/api/dashboard/machine-utilization",
        "/api/analytics/export",
        "/api/audit-logs",
        "/api/notifications",
        "/api/search",
        "/api/settings",
    }
    assert expected.issubset(paths)


def test_dashboard_kpis_charts_and_csv_export(db: Session) -> None:
    summary = dashboard_router.get_dashboard_summary(db=db)
    kpis = summary["kpis"]
    assert kpis["total_orders"] == 30
    assert kpis["total_machines"] == 8
    assert kpis["total_materials"] == 25
    assert kpis["scheduled_orders"] == 6
    assert 0 <= kpis["on_time_delivery_pct"] <= 100
    assert len(summary["upcoming_schedule"]) > 0

    charts = dashboard_router.get_production_charts(db=db)
    assert sum(charts["order_status_chart"]["values"]) == 30
    assert sum(charts["priority_chart"]["values"]) == 30

    util = dashboard_router.get_machine_utilization_charts(db=db)
    assert len(util["machines"]) == 8

    csv_resp = dashboard_router.export_analytics_csv(db=db)
    csv_text = csv_resp.body.decode("utf-8")
    assert "run_id,run_name,solver_status" in csv_text
    assert "RUN-2026-000001" in csv_text


def test_audit_search_notifications_and_settings(db: Session) -> None:
    logs = audit_router.list_audit_logs(limit=100, db=db)
    assert len(logs) >= 1

    notifs = audit_router.list_notifications(db=db)
    assert notifs["unread_count"] >= 1
    first_id = notifs["items"][0].id
    audit_router.mark_notification_read(first_id, db=db)
    assert audit_router.list_notifications(db=db)["unread_count"] == 0

    search_res = audit_router.global_search(q="ORD-2026", db=db)
    assert len(search_res["orders"]) >= 1

    updated = audit_router.update_system_settings(
        SettingsUpdate(
            default_solver_time_limit_seconds=45,
            default_weight_makespan=1.0,
            default_weight_lateness=4.0,
            default_weight_changeover=1.0,
            plant_name="PlantOps Demo Plant",
            default_shift_hours="08:00 - 16:00",
        ),
        db=db,
    )
    assert updated["default_solver_time_limit_seconds"] == 45


def test_jwt_authentication_and_rbac_permissions(db: Session) -> None:
    # Password hashing check
    hashed = hash_password("Secret123!")
    assert verify_password("Secret123!", hashed) is True
    assert verify_password("WrongPass", hashed) is False

    # Login with seeded demo user
    login_res = auth_router.login(
        LoginRequest(username="planner", password="PlantOps@2026"), db=db
    )
    assert login_res["token_type"] == "bearer"
    assert "Production Planner" in login_res["user"]["roles"]

    decoded = decode_access_token(login_res["access_token"])
    assert decoded["username"] == "planner"

    # Register new user
    reg = auth_router.register(
        RegisterRequest(
            username="new_operator",
            email="newop@plantops.com",
            full_name="New Operator",
            password="OpPassword1!",
        ),
        db=db,
    )
    assert "Plant Operator" in reg["roles"]

    # Admin user management
    created = users_router.create_user_by_admin(
        AdminUserCreate(
            username="qa_lead",
            email="qalead@plantops.com",
            full_name="QA Lead",
            password="QaPassword1!",
            role_name="Maintenance/Quality Engineer",
        ),
        db=db,
    )
    assert created["roles"] == ["Maintenance/Quality Engineer"]

    updated_role = users_router.update_user_role(
        created["user_id"], RoleUpdateRequest(role_name="Production Planner"), db=db
    )
    assert updated_role["roles"] == ["Production Planner"]

    # Backend RBAC enforcement checks
    admin_only_guard = require_roles("Admin")
    planner_user = {"user_id": "USR-002", "username": "planner", "roles": ["Production Planner"]}
    admin_user = {"user_id": "USR-001", "username": "admin", "roles": ["Admin"]}

    assert admin_only_guard(admin_user)["username"] == "admin"
    with pytest.raises(HTTPException) as exc:
        admin_only_guard(planner_user)
    assert exc.value.status_code == 403

    # Missing token must raise 401
    with pytest.raises(HTTPException) as auth_exc:
        get_current_user(credentials=None, db=db)
    assert auth_exc.value.status_code == 401
