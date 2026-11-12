"""
FastAPI router for Overview Dashboard KPIs, Chart.js Datasets, Analytics,
and Real Database CSV Report Export.
"""

from collections import Counter, defaultdict
import csv
from datetime import date
import io
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.models import (
    AuditLog,
    ConstraintViolation,
    Machine,
    MachineCalendar,
    Material,
    OperationSchedule,
    ProductionOrder,
    SchedulingRun,
)
from app.models.enums import MachineStatus, OrderStatus, ResolutionStatus


router = APIRouter(prefix="/api", tags=["Dashboard & Analytics"])


@router.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """Calculate all 12 real-time KPI cards, upcoming schedule, alerts, and recent activity."""
    orders = db.query(ProductionOrder).all()
    machines = db.query(Machine).all()
    total_materials = db.query(Material).count()
    open_violations = (
        db.query(ConstraintViolation)
        .filter(ConstraintViolation.resolution_status.in_([ResolutionStatus.OPEN.value, ResolutionStatus.IN_REVIEW.value]))
        .count()
    )

    latest_run = db.query(SchedulingRun).order_by(SchedulingRun.started_at.desc()).first()

    total_orders = len(orders)
    pending_orders = sum(
        1 for o in orders if o.status in (OrderStatus.DRAFT.value, OrderStatus.RELEASED.value, OrderStatus.PLANNED.value)
    )
    scheduled_orders = sum(1 for o in orders if o.status == OrderStatus.SCHEDULED.value)
    completed_orders = sum(1 for o in orders if o.status == OrderStatus.COMPLETED.value)
    delayed_orders = sum(1 for o in orders if o.status == OrderStatus.DELAYED.value)
    infeasible_orders = sum(1 for o in orders if o.status == OrderStatus.INFEASIBLE.value)

    total_machines = len(machines)
    available_machines = sum(
        1 for m in machines if m.status in (MachineStatus.AVAILABLE.value, MachineStatus.RUNNING.value)
    )

    # Calculate Average Machine Utilization from latest run + calendar
    total_avail_mins = sum(c.available_minutes for c in db.query(MachineCalendar).all())
    total_sched_mins = 0
    if latest_run:
        total_sched_mins = sum(
            s.duration_minutes
            for s in db.query(OperationSchedule)
            .filter(OperationSchedule.run_id == latest_run.run_id)
            .all()
        )
    avg_util = round((total_sched_mins / total_avail_mins) * 100.0, 2) if total_avail_mins > 0 else 0.0

    # On-Time Delivery %
    if latest_run and latest_run.on_time_delivery_pct > 0:
        otd_pct = latest_run.on_time_delivery_pct
    else:
        delivered_or_sched = scheduled_orders + completed_orders + delayed_orders
        otd_pct = (
            round(((delivered_or_sched - delayed_orders) / delivered_or_sched) * 100.0, 2)
            if delivered_or_sched > 0
            else 100.0
        )

    # Upcoming Schedule (top 10 from latest run)
    upcoming = []
    if latest_run:
        sch_rows = (
            db.query(OperationSchedule)
            .filter(OperationSchedule.run_id == latest_run.run_id)
            .order_by(OperationSchedule.start_time.asc())
            .limit(10)
            .all()
        )
        upcoming = [
            {
                "schedule_id": s.schedule_id,
                "order_id": s.order_id,
                "operation_id": s.order_operation_id,
                "machine_id": s.machine_id,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "is_late": s.is_late,
            }
            for s in sch_rows
        ]

    # Critical Alerts (open critical exceptions + delayed materials + urgent orders)
    alerts = [
        {
            "id": v.anomaly_id,
            "severity": v.severity,
            "title": v.issue_type,
            "message": v.explanation,
            "entity_id": v.entity_id,
        }
        for v in db.query(ConstraintViolation)
        .filter(ConstraintViolation.resolution_status == ResolutionStatus.OPEN.value)
        .order_by(ConstraintViolation.created_at.desc())
        .limit(5)
        .all()
    ]
    if not alerts:
        # Surface low/delayed material & urgent order operational alerts
        delayed_mats = db.query(Material).filter(Material.stock_status == "Delayed").limit(3).all()
        for mat in delayed_mats:
            alerts.append(
                {
                    "id": mat.material_id,
                    "severity": "Warning",
                    "title": "Delayed Material Lot",
                    "message": f"{mat.name} ({mat.material_id}) has delayed inventory delivery.",
                    "entity_id": mat.material_id,
                }
            )

    recent_activities = [
        {
            "id": a.id,
            "username": a.username,
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "reason": a.reason,
            "created_at": a.created_at.isoformat(),
        }
        for a in db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()
    ]

    return {
        "kpis": {
            "total_orders": total_orders,
            "pending_orders": pending_orders,
            "scheduled_orders": scheduled_orders,
            "completed_orders": completed_orders,
            "delayed_orders": delayed_orders,
            "infeasible_orders": infeasible_orders,
            "total_machines": total_machines,
            "available_machines": available_machines,
            "avg_machine_utilization_pct": avg_util,
            "total_materials": total_materials,
            "open_constraint_violations": open_violations,
            "on_time_delivery_pct": otd_pct,
        },
        "latest_run_id": latest_run.run_id if latest_run else None,
        "upcoming_schedule": upcoming,
        "critical_alerts": alerts,
        "recent_activities": recent_activities,
    }


@router.get("/dashboard/production")
def get_production_charts(
    start_date: date | None = None,
    end_date: date | None = None,
    machine_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Return Chart.js datasets for order status, output trend, priorities, and violations."""
    orders_query = db.query(ProductionOrder)
    if start_date:
        orders_query = orders_query.filter(ProductionOrder.release_date >= start_date)
    if end_date:
        orders_query = orders_query.filter(ProductionOrder.release_date <= end_date)
    orders = orders_query.all()

    status_counts = Counter(o.status for o in orders)
    priority_counts = Counter(f"P{o.priority}" for o in orders)

    # Production output trend grouped by scheduled date
    sched_query = db.query(OperationSchedule)
    if machine_id:
        sched_query = sched_query.filter(OperationSchedule.machine_id == machine_id)
    schedules = sched_query.order_by(OperationSchedule.start_time.asc()).all()

    output_by_day: dict[str, int] = defaultdict(int)
    for s in schedules:
        day_key = s.start_time.strftime("%Y-%m-%d")
        output_by_day[day_key] += s.duration_minutes

    violations = db.query(ConstraintViolation).all()
    violation_counts = Counter(v.issue_type for v in violations)

    return {
        "order_status_chart": {
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        },
        "priority_chart": {
            "labels": ["P1", "P2", "P3", "P4", "P5"],
            "values": [priority_counts.get(f"P{i}", 0) for i in range(1, 6)],
        },
        "production_output_chart": {
            "labels": list(output_by_day.keys()),
            "values": list(output_by_day.values()),
        },
        "constraint_violations_chart": {
            "labels": list(violation_counts.keys()) if violation_counts else ["No Open Violations"],
            "values": list(violation_counts.values()) if violation_counts else [0],
        },
    }


@router.get("/dashboard/machine-utilization")
def get_machine_utilization_charts(
    run_id: str | None = None,
    machine_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Return per-machine utilization percentages and availability status counts."""
    if not run_id:
        latest = db.query(SchedulingRun).order_by(SchedulingRun.started_at.desc()).first()
        run_id = latest.run_id if latest else None

    machines_q = db.query(Machine)
    if machine_id:
        machines_q = machines_q.filter(Machine.machine_id == machine_id)
    machines = machines_q.order_by(Machine.machine_id).all()

    cal_mins_by_mach: dict[str, int] = defaultdict(int)
    for c in db.query(MachineCalendar).all():
        cal_mins_by_mach[c.machine_id] += c.available_minutes

    sched_mins_by_mach: dict[str, int] = defaultdict(int)
    if run_id:
        for s in db.query(OperationSchedule).filter(OperationSchedule.run_id == run_id).all():
            sched_mins_by_mach[s.machine_id] += s.duration_minutes

    per_machine = []
    for m in machines:
        avail = cal_mins_by_mach.get(m.machine_id, 0)
        sched = sched_mins_by_mach.get(m.machine_id, 0)
        util = round((sched / avail) * 100.0, 2) if avail > 0 else 0.0
        per_machine.append(
            {
                "machine_id": m.machine_id,
                "machine_name": m.name,
                "status": m.status,
                "scheduled_minutes": sched,
                "available_minutes": avail,
                "utilization_pct": util,
            }
        )

    status_counts = Counter(m.status for m in db.query(Machine).all())
    return {
        "run_id": run_id,
        "machines": per_machine,
        "availability_chart": {
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        },
    }


@router.get("/analytics/export")
def export_analytics_csv(run_id: str | None = None, db: Session = Depends(get_db)):
    """Export real scheduling & order performance metrics as downloadable CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "run_id",
            "run_name",
            "solver_status",
            "makespan_minutes",
            "total_lateness_minutes",
            "total_changeover_minutes",
            "delayed_order_count",
            "on_time_delivery_pct",
            "avg_machine_utilization_pct",
            "execution_duration_seconds",
        ]
    )
    query = db.query(SchedulingRun)
    if run_id:
        query = query.filter(SchedulingRun.run_id == run_id)
    for r in query.order_by(SchedulingRun.started_at.desc()).all():
        writer.writerow(
            [
                r.run_id,
                r.run_name,
                r.solver_status,
                r.makespan_minutes,
                r.total_lateness_minutes,
                r.total_changeover_minutes,
                r.delayed_order_count,
                r.on_time_delivery_pct,
                r.avg_machine_utilization_pct,
                r.execution_duration_seconds,
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantops_analytics_report.csv"},
    )
