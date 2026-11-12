"""Pydantic schemas for Machines, Calendars, Downtime, Labor Shifts, and Shared Tooling."""

from datetime import date, datetime, time
from pydantic import BaseModel, ConfigDict, Field


class MachineCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    machine_type: str = Field(..., min_length=2, max_length=60)
    work_center: str = Field(..., min_length=2, max_length=60)
    capacity_per_hour: float = Field(10.0, gt=0)
    concurrent_job_capacity: int = Field(1, ge=1)
    capabilities: str | None = None
    hourly_operating_cost: float = Field(50.0, ge=0)


class MachineUpdate(BaseModel):
    name: str | None = None
    machine_type: str | None = None
    work_center: str | None = None
    capacity_per_hour: float | None = Field(None, gt=0)
    concurrent_job_capacity: int | None = Field(None, ge=1)
    capabilities: str | None = None
    hourly_operating_cost: float | None = Field(None, ge=0)
    status: str | None = None


class MachineOut(BaseModel):
    machine_id: str
    name: str
    machine_type: str
    work_center: str
    capacity_per_hour: float
    concurrent_job_capacity: int
    capabilities: str | None = None
    hourly_operating_cost: float
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalendarCreate(BaseModel):
    machine_id: str
    calendar_date: date
    is_working_day: bool = True
    is_holiday: bool = False
    shift_name: str = "Day Shift"
    shift_start_time: time = time(8, 0)
    shift_end_time: time = time(16, 0)
    break_start_time: time | None = time(12, 0)
    break_end_time: time | None = time(12, 30)
    notes: str | None = None


class CalendarOut(BaseModel):
    calendar_id: int
    machine_id: str
    calendar_date: date
    day_of_week: str
    is_working_day: bool
    is_holiday: bool
    shift_name: str
    shift_start_time: time
    shift_end_time: time
    break_start_time: time | None = None
    break_end_time: time | None = None
    available_minutes: int
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DowntimeCreate(BaseModel):
    machine_id: str
    downtime_type: str = "Planned Maintenance"
    start_time: datetime
    end_time: datetime
    reason: str = Field(..., min_length=3, max_length=255)


class DowntimeOut(BaseModel):
    downtime_id: int
    machine_id: str
    downtime_type: str
    start_time: datetime
    end_time: datetime
    reason: str
    reported_by: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class LaborShiftCreate(BaseModel):
    shift_name: str = "Day Shift"
    shift_date: date
    start_time: time = time(8, 0)
    end_time: time = time(16, 0)
    break_minutes: int = Field(30, ge=0)
    total_headcount: int = Field(20, ge=1)
    available_headcount: int = Field(20, ge=0)


class LaborShiftOut(BaseModel):
    shift_id: int
    shift_name: str
    shift_date: date
    start_time: time
    end_time: time
    break_minutes: int
    total_headcount: int
    available_headcount: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class ToolingOut(BaseModel):
    tooling_id: str
    name: str
    tool_type: str
    total_quantity: int
    available_quantity: int
    status: str

    model_config = ConfigDict(from_attributes=True)

