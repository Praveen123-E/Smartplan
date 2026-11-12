"""FastAPI router for OR-Tools Production Scheduling, Gantt Data, Metrics, and Run Comparison."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models.enums import RoleName
from app.models import (
    Machine,
    MachineCalendar,
    MachineDowntime,
    OperationSchedule,
    ProductionOrder,
    ProductionOrderOperation,
    SchedulingRun,
)
from app.scheduling.solver import run_production_scheduling
from app.schemas.scheduling import (
    OperationScheduleOut,
    SchedulingRunOut,
    SchedulingRunRequest,
)


router = APIRouter(prefix="/api/scheduling", tags=["Scheduling Engine & Gantt"])


@router.post(
    "/run",
    response_model=SchedulingRunOut,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def trigger_scheduling_run(payload: SchedulingRunRequest, db: Session = Depends(get_db)):
    try:
        return run_production_scheduling(db, payload, triggered_by="planner")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/runs", response_model=list[SchedulingRunOut])
def list_scheduling_runs(db: Session = Depends(get_db)):
    return db.query(SchedulingRun).order_by(SchedulingRun.started_at.desc()).all()


@router.get("/compare")
def compare_scheduling_runs(
    run_ids: str = Query(..., description="Comma-separated run IDs to compare"),
    db: Session = Depends(get_db),
):
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two run_ids to compare.")

    runs = (
        db.query(SchedulingRun)
        .filter(SchedulingRun.run_id.in_(ids))
        .order_by(SchedulingRun.started_at.asc())
        .all()
    )
    if len(runs) != len(ids):
        raise HTTPException(status_code=404, detail="One or more requested run_ids were not found.")

    baseline = runs[0]
    comparison = []
    for r in runs:
        comparison.append(
            {
                "run_id": r.run_id,
                "run_name": r.run_name,
                "solver_status": r.solver_status,
                "makespan_minutes": r.makespan_minutes,
                "makespan_delta": r.makespan_minutes - baseline.makespan_minutes,
                "total_lateness_minutes": r.total_lateness_minutes,
                "lateness_delta": r.total_lateness_minutes - baseline.total_lateness_minutes,
                "total_changeover_minutes": r.total_changeover_minutes,
                "changeover_delta": r.total_changeover_minutes - baseline.total_changeover_minutes,
                "delayed_order_count": r.delayed_order_count,
                "on_time_delivery_pct": r.on_time_delivery_pct,
                "avg_machine_utilization_pct": r.avg_machine_utilization_pct,
                "execution_duration_seconds": r.execution_duration_seconds,
            }
        )
    return {"baseline_run_id": baseline.run_id, "runs": comparison}


@router.get("/runs/{run_id}")
def get_scheduling_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SchedulingRun).filter(SchedulingRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Scheduling run '{run_id}' not found.")

    schedules = (
        db.query(OperationSchedule)
        .filter(OperationSchedule.run_id == run_id)
        .order_by(OperationSchedule.start_time)
        .all()
    )
    return {
        "run": SchedulingRunOut.model_validate(run),
        "schedules": [OperationScheduleOut.model_validate(s) for s in schedules],
    }


@router.get("/runs/{run_id}/gantt")
def get_run_gantt_data(
    run_id: str,
    machine_id: str | None = None,
    order_id: str | None = None,
    db: Session = Depends(get_db),
):
    run = db.query(SchedulingRun).filter(SchedulingRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Scheduling run '{run_id}' not found.")

    sched_query = db.query(OperationSchedule).filter(OperationSchedule.run_id == run_id)
    if machine_id:
        sched_query = sched_query.filter(OperationSchedule.machine_id == machine_id)
    if order_id:
        sched_query = sched_query.filter(OperationSchedule.order_id == order_id)
    schedules = sched_query.order_by(OperationSchedule.machine_id, OperationSchedule.start_time).all()

    orders_map = {o.order_id: o for o in db.query(ProductionOrder).all()}
    ops_map = {op.operation_id: op for op in db.query(ProductionOrderOperation).all()}

    tasks = []
    used_machines = set()
    for s in schedules:
        used_machines.add(s.machine_id)
        ord_obj = orders_map.get(s.order_id)
        op_obj = ops_map.get(s.order_operation_id)
        tasks.append(
            {
                "schedule_id": s.schedule_id,
                "machine_id": s.machine_id,
                "order_id": s.order_id,
                "operation_id": s.order_operation_id,
                "operation_code": op_obj.operation_code if op_obj else None,
                "sequence_number": op_obj.sequence_number if op_obj else None,
                "product_id": ord_obj.product_id if ord_obj else None,
                "priority": ord_obj.priority if ord_obj else 3,
                "is_urgent": ord_obj.is_urgent if ord_obj else False,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "duration_minutes": s.duration_minutes,
                "changeover_minutes": s.changeover_minutes,
                "changeover_start_time": s.changeover_start_time.isoformat()
                if s.changeover_start_time
                else None,
                "is_late": s.is_late,
                "lateness_minutes": s.lateness_minutes,
            }
        )

    mach_query = db.query(Machine)
    if machine_id:
        mach_query = mach_query.filter(Machine.machine_id == machine_id)
    machines_list = mach_query.order_by(Machine.machine_id).all()

    dt_query = db.query(MachineDowntime)
    if machine_id:
        dt_query = dt_query.filter(MachineDowntime.machine_id == machine_id)
    downtimes = [
        {
            "downtime_id": d.downtime_id,
            "machine_id": d.machine_id,
            "downtime_type": d.downtime_type,
            "start_time": d.start_time.isoformat(),
            "end_time": d.end_time.isoformat(),
            "reason": d.reason,
        }
        for d in dt_query.all()
    ]

    cal_query = db.query(MachineCalendar)
    if machine_id:
        cal_query = cal_query.filter(MachineCalendar.machine_id == machine_id)
    shift_windows = [
        {
            "machine_id": c.machine_id,
            "date": str(c.calendar_date),
            "is_working_day": c.is_working_day,
            "is_holiday": c.is_holiday,
            "shift_start": str(c.shift_start_time),
            "shift_end": str(c.shift_end_time),
        }
        for c in cal_query.limit(500).all()
    ]

    return {
        "run": SchedulingRunOut.model_validate(run),
        "machines": [
            {"machine_id": m.machine_id, "name": m.name, "machine_type": m.machine_type, "status": m.status}
            for m in machines_list
        ],
        "tasks": tasks,
        "downtimes": downtimes,
        "shift_windows": shift_windows,
    }


@router.get("/runs/{run_id}/metrics")
def get_run_metrics(run_id: str, db: Session = Depends(get_db)):
    run = db.query(SchedulingRun).filter(SchedulingRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Scheduling run '{run_id}' not found.")

    schedules = db.query(OperationSchedule).filter(OperationSchedule.run_id == run_id).all()
    order_ids = {s.order_id for s in schedules}
    avg_lateness = (
        round(run.total_lateness_minutes / max(1, len(order_ids)), 2)
        if order_ids
        else 0.0
    )
    total_run_minutes = sum(s.duration_minutes for s in schedules)
    return {
        "run_id": run.run_id,
        "run_name": run.run_name,
        "solver_status": run.solver_status,
        "objective_value": run.objective_value,
        "best_bound": run.best_bound,
        "execution_duration_seconds": run.execution_duration_seconds,
        "scheduled_orders": len(order_ids),
        "scheduled_operations": len(schedules),
        "makespan_minutes": run.makespan_minutes,
        "total_lateness_minutes": run.total_lateness_minutes,
        "average_lateness_minutes": avg_lateness,
        "total_changeover_minutes": run.total_changeover_minutes,
        "delayed_order_count": run.delayed_order_count,
        "unscheduled_operation_count": run.unscheduled_operation_count,
        "on_time_delivery_pct": run.on_time_delivery_pct,
        "avg_machine_utilization_pct": run.avg_machine_utilization_pct,
        "total_productive_minutes": total_run_minutes,
        "infeasibility_reason": run.infeasibility_reason,
    }
