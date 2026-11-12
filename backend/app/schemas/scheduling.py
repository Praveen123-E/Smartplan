"""Pydantic schemas for Scheduling Runs, Operation Schedules, Gantt, and Run Comparison."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class SchedulingRunRequest(BaseModel):
    run_name: str = Field("Planner Schedule Run", min_length=2, max_length=120)
    order_ids: list[str] | None = None
    max_orders: int = Field(25, ge=1, le=500)
    weight_makespan: float = Field(1.0, ge=0.0)
    weight_lateness: float = Field(3.0, ge=0.0)
    weight_changeover: float = Field(1.5, ge=0.0)
    solver_time_limit_seconds: int = Field(15, ge=1, le=300)


class SchedulingRunOut(BaseModel):
    run_id: str
    run_name: str
    solver_status: str
    objective_value: float | None = None
    best_bound: float | None = None
    execution_duration_seconds: float
    makespan_minutes: int
    total_lateness_minutes: int
    total_changeover_minutes: int
    delayed_order_count: int
    unscheduled_operation_count: int
    on_time_delivery_pct: float
    avg_machine_utilization_pct: float
    weight_makespan: float
    weight_lateness: float
    weight_changeover: float
    solver_time_limit_seconds: int
    infeasibility_reason: str | None = None
    triggered_by: str | None = None
    is_baseline: bool
    started_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OperationScheduleOut(BaseModel):
    schedule_id: str
    run_id: str
    order_id: str
    order_operation_id: str
    machine_id: str
    labor_shift_id: int | None = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    changeover_minutes: int
    changeover_start_time: datetime | None = None
    is_late: bool
    lateness_minutes: int
    status: str

    model_config = ConfigDict(from_attributes=True)

