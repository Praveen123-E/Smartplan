"""
Business logic for Machines, Utilization Calculation, Calendars, Downtime,
Labor Shifts, and Shared Tooling.

Machine Utilization Formula:
    utilization_pct = (total_scheduled_minutes / total_available_calendar_minutes) * 100
Calculated from actual OperationSchedule and MachineCalendar database rows.
"""

from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    LaborShift,
    Machine,
    MachineCalendar,
    MachineDowntime,
    OperationSchedule,
    SchedulingRun,
    SharedTooling,
)
from app.models.enums import MachineStatus
from app.schemas.machines import (
    CalendarCreate,
    DowntimeCreate,
    LaborShiftCreate,
    MachineCreate,
    MachineUpdate,
)
from app.services.audit_service import record_audit_log, record_state_change
from app.utils.id_generator import format_machine_id, next_numeric_suffix


def list_machines(
    db: Session,
    search: str | None = None,
    machine_type: str | None = None,
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[int, list[Machine]]:
    query = db.query(Machine)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Machine.machine_id.ilike(like))
            | (Machine.name.ilike(like))
            | (Machine.work_center.ilike(like))
        )
    if machine_type:
        query = query.filter(Machine.machine_type == machine_type)
    if status_filter:
        query = query.filter(Machine.status == status_filter)

    total = query.count()
    items = (
        query.order_by(Machine.machine_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def create_machine(db: Session, payload: MachineCreate, username: str = "system") -> Machine:
    counter = next_numeric_suffix(db, Machine, Machine.machine_id, "MACH-")
    machine = Machine(
        machine_id=format_machine_id(counter),
        name=payload.name,
        machine_type=payload.machine_type,
        work_center=payload.work_center,
        capacity_per_hour=payload.capacity_per_hour,
        concurrent_job_capacity=payload.concurrent_job_capacity,
        capabilities=payload.capabilities,
        hourly_operating_cost=payload.hourly_operating_cost,
        status=MachineStatus.AVAILABLE.value,
    )
    db.add(machine)
    record_audit_log(
        db,
        username=username,
        action="CREATE_MACHINE",
        entity_type="Machine",
        entity_id=machine.machine_id,
        new_value={"name": machine.name, "machine_type": machine.machine_type},
    )
    db.commit()
    db.refresh(machine)
    return machine


def update_machine(
    db: Session, machine_id: str, payload: MachineUpdate, username: str = "system"
) -> Machine:
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail=f"Machine '{machine_id}' not found.")

    old_status = machine.status
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] not in {e.value for e in MachineStatus}:
        raise HTTPException(status_code=400, detail=f"Invalid machine status '{updates['status']}'.")

    for field, val in updates.items():
        setattr(machine, field, val)

    if "status" in updates and updates["status"] != old_status:
        record_state_change(
            db,
            entity_type="Machine",
            entity_id=machine.machine_id,
            previous_state=old_status,
            new_state=updates["status"],
            changed_by=username,
            reason="Machine status updated",
        )
    record_audit_log(
        db,
        username=username,
        action="UPDATE_MACHINE",
        entity_type="Machine",
        entity_id=machine.machine_id,
        old_value={"status": old_status},
        new_value=updates,
    )
    db.commit()
    db.refresh(machine)
    return machine


def calculate_machine_utilization(
    db: Session, machine_id: str, run_id: str | None = None
) -> dict:
    """
    Calculate machine utilization from real calendar and schedule records.

    Formula:
        utilization_pct = (scheduled_minutes / available_calendar_minutes) * 100
    """
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail=f"Machine '{machine_id}' not found.")

    if not run_id:
        latest_run = db.query(SchedulingRun).order_by(SchedulingRun.started_at.desc()).first()
        run_id = latest_run.run_id if latest_run else None

    available_minutes = (
        db.query(func.coalesce(func.sum(MachineCalendar.available_minutes), 0))
        .filter(MachineCalendar.machine_id == machine_id)
        .scalar()
        or 0
    )

    scheduled_minutes = 0
    changeover_minutes = 0
    operation_count = 0
    if run_id:
        schedules = (
            db.query(OperationSchedule)
            .filter(
                OperationSchedule.machine_id == machine_id,
                OperationSchedule.run_id == run_id,
            )
            .all()
        )
        operation_count = len(schedules)
        scheduled_minutes = sum(s.duration_minutes for s in schedules)
        changeover_minutes = sum(s.changeover_minutes for s in schedules)

    utilization_pct = (
        round((scheduled_minutes / available_minutes) * 100.0, 2)
        if available_minutes > 0
        else 0.0
    )
    idle_minutes = max(0, int(available_minutes) - int(scheduled_minutes) - int(changeover_minutes))

    return {
        "machine_id": machine.machine_id,
        "machine_name": machine.name,
        "status": machine.status,
        "run_id": run_id,
        "available_calendar_minutes": int(available_minutes),
        "scheduled_minutes": int(scheduled_minutes),
        "changeover_minutes": int(changeover_minutes),
        "idle_minutes": idle_minutes,
        "operation_count": operation_count,
        "utilization_pct": utilization_pct,
        "formula": "utilization_pct = (scheduled_minutes / available_calendar_minutes) * 100",
    }


def create_machine_calendar(
    db: Session, payload: CalendarCreate, username: str = "system"
) -> MachineCalendar:
    if not db.query(Machine).filter(Machine.machine_id == payload.machine_id).first():
        raise HTTPException(status_code=404, detail=f"Machine '{payload.machine_id}' not found.")
    if payload.is_holiday and payload.is_working_day:
        raise HTTPException(status_code=400, detail="A holiday cannot be marked as a working day.")
    if payload.shift_end_time <= payload.shift_start_time:
        raise HTTPException(status_code=400, detail="shift_end_time must be after shift_start_time.")

    # Compute available minutes dynamically
    if not payload.is_working_day or payload.is_holiday:
        avail_mins = 0
    else:
        s_dt = datetime.combine(payload.calendar_date, payload.shift_start_time)
        e_dt = datetime.combine(payload.calendar_date, payload.shift_end_time)
        total = int((e_dt - s_dt).total_seconds() // 60)
        break_mins = 0
        if payload.break_start_time and payload.break_end_time:
            if payload.break_end_time <= payload.break_start_time:
                raise HTTPException(status_code=400, detail="break_end_time must be after break_start_time.")
            bs = datetime.combine(payload.calendar_date, payload.break_start_time)
            be = datetime.combine(payload.calendar_date, payload.break_end_time)
            break_mins = int((be - bs).total_seconds() // 60)
        avail_mins = max(0, total - break_mins)

    cal = MachineCalendar(
        machine_id=payload.machine_id,
        calendar_date=payload.calendar_date,
        day_of_week=payload.calendar_date.strftime("%A"),
        is_working_day=payload.is_working_day,
        is_holiday=payload.is_holiday,
        shift_name=payload.shift_name,
        shift_start_time=payload.shift_start_time,
        shift_end_time=payload.shift_end_time,
        break_start_time=payload.break_start_time,
        break_end_time=payload.break_end_time,
        available_minutes=avail_mins,
        notes=payload.notes,
    )
    db.add(cal)
    record_audit_log(
        db,
        username=username,
        action="CREATE_CALENDAR",
        entity_type="MachineCalendar",
        entity_id=f"{payload.machine_id}:{payload.calendar_date}",
        new_value={"available_minutes": avail_mins, "is_working_day": payload.is_working_day},
    )
    db.commit()
    db.refresh(cal)
    return cal


def create_downtime(
    db: Session, payload: DowntimeCreate, username: str = "system"
) -> MachineDowntime:
    if not db.query(Machine).filter(Machine.machine_id == payload.machine_id).first():
        raise HTTPException(status_code=404, detail=f"Machine '{payload.machine_id}' not found.")
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="Downtime end_time must be after start_time.")

    dt = MachineDowntime(
        machine_id=payload.machine_id,
        downtime_type=payload.downtime_type,
        start_time=payload.start_time,
        end_time=payload.end_time,
        reason=payload.reason,
        reported_by=username,
        status="Scheduled",
    )
    db.add(dt)
    record_audit_log(
        db,
        username=username,
        action="CREATE_DOWNTIME",
        entity_type="MachineDowntime",
        entity_id=payload.machine_id,
        new_value={"start": str(payload.start_time), "end": str(payload.end_time), "reason": payload.reason},
    )
    db.commit()
    db.refresh(dt)
    return dt


def create_labor_shift(
    db: Session, payload: LaborShiftCreate, username: str = "system"
) -> LaborShift:
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=400, detail="Shift end_time must be after start_time.")
    if payload.available_headcount > payload.total_headcount:
        raise HTTPException(status_code=400, detail="available_headcount cannot exceed total_headcount.")

    shift = LaborShift(**payload.model_dump())
    db.add(shift)
    record_audit_log(
        db,
        username=username,
        action="CREATE_LABOR_SHIFT",
        entity_type="LaborShift",
        entity_id=f"{payload.shift_date}:{payload.shift_name}",
        new_value={"available_headcount": payload.available_headcount},
    )
    db.commit()
    db.refresh(shift)
    return shift

