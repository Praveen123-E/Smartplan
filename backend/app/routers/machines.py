"""FastAPI router for Machines, Calendars, Downtime, Labor Shifts, and Shared Tooling."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import require_roles
from app.database.connection import get_db
from app.models import LaborShift, Machine, MachineCalendar, MachineDowntime, SharedTooling
from app.models.enums import RoleName
from app.schemas.common import PaginatedResponse
from app.schemas.machines import (
    CalendarCreate,
    CalendarOut,
    DowntimeCreate,
    DowntimeOut,
    LaborShiftCreate,
    LaborShiftOut,
    MachineCreate,
    MachineOut,
    MachineUpdate,
    ToolingOut,
)
from app.services import machine_service


router = APIRouter(prefix="/api", tags=["Machines & Calendars"])


@router.get("/machines", response_model=PaginatedResponse[MachineOut])
def get_machines(
    search: str | None = None,
    machine_type: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    total, items = machine_service.list_machines(db, search, machine_type, status, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post(
    "/machines",
    response_model=MachineOut,
    status_code=201,
    dependencies=[Depends(require_roles(RoleName.ADMIN.value, RoleName.PRODUCTION_PLANNER.value))],
)
def create_machine(payload: MachineCreate, db: Session = Depends(get_db)):
    return machine_service.create_machine(db, payload)


@router.get("/machines/{machine_id}")
def get_machine(machine_id: str, db: Session = Depends(get_db)):
    machine = db.query(Machine).filter(Machine.machine_id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail=f"Machine '{machine_id}' not found.")
    utilization = machine_service.calculate_machine_utilization(db, machine_id)
    downtime = (
        db.query(MachineDowntime)
        .filter(MachineDowntime.machine_id == machine_id)
        .order_by(MachineDowntime.start_time.desc())
        .all()
    )
    return {
        "machine": MachineOut.model_validate(machine),
        "utilization": utilization,
        "downtime": [DowntimeOut.model_validate(d) for d in downtime],
    }


@router.put("/machines/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: str, payload: MachineUpdate, db: Session = Depends(get_db)):
    return machine_service.update_machine(db, machine_id, payload)


@router.get("/machines/{machine_id}/utilization")
def get_machine_utilization(
    machine_id: str, run_id: str | None = None, db: Session = Depends(get_db)
):
    return machine_service.calculate_machine_utilization(db, machine_id, run_id)


@router.get("/calendars", response_model=list[CalendarOut])
def list_calendars(
    machine_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(MachineCalendar)
    if machine_id:
        query = query.filter(MachineCalendar.machine_id == machine_id)
    if from_date:
        query = query.filter(MachineCalendar.calendar_date >= from_date)
    if to_date:
        query = query.filter(MachineCalendar.calendar_date <= to_date)
    return query.order_by(MachineCalendar.calendar_date, MachineCalendar.machine_id).limit(500).all()


@router.post("/calendars", response_model=CalendarOut, status_code=201)
def create_calendar(payload: CalendarCreate, db: Session = Depends(get_db)):
    return machine_service.create_machine_calendar(db, payload)


@router.get("/downtime", response_model=list[DowntimeOut])
def list_downtime(machine_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(MachineDowntime)
    if machine_id:
        query = query.filter(MachineDowntime.machine_id == machine_id)
    return query.order_by(MachineDowntime.start_time.desc()).all()


@router.post(
    "/downtime",
    response_model=DowntimeOut,
    status_code=201,
    dependencies=[
        Depends(
            require_roles(
                RoleName.ADMIN.value,
                RoleName.MAINTENANCE_QUALITY_ENGINEER.value,
                RoleName.PLANT_OPERATOR.value,
            )
        )
    ],
)
def create_downtime(payload: DowntimeCreate, db: Session = Depends(get_db)):
    return machine_service.create_downtime(db, payload)


@router.get("/labor-shifts", response_model=list[LaborShiftOut])
def list_labor_shifts(db: Session = Depends(get_db)):
    return db.query(LaborShift).order_by(LaborShift.shift_date, LaborShift.shift_name).all()


@router.post("/labor-shifts", response_model=LaborShiftOut, status_code=201)
def create_labor_shift(payload: LaborShiftCreate, db: Session = Depends(get_db)):
    return machine_service.create_labor_shift(db, payload)


@router.get("/tooling", response_model=list[ToolingOut])
def list_tooling(db: Session = Depends(get_db)):
    return db.query(SharedTooling).order_by(SharedTooling.tooling_id).all()
