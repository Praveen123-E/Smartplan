"""Pydantic schemas for Production Orders, Operations, and Changeover Matrix."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    product_id: str
    routing_id: str | None = None
    quantity: int = Field(..., gt=0)
    priority: int = Field(3, ge=1, le=5)
    customer_name: str | None = None
    release_date: datetime
    due_date: datetime
    notes: str | None = None


class OrderUpdate(BaseModel):
    quantity: int | None = Field(None, gt=0)
    priority: int | None = Field(None, ge=1, le=5)
    customer_name: str | None = None
    release_date: datetime | None = None
    due_date: datetime | None = None
    notes: str | None = None


class OrderStatusUpdate(BaseModel):
    new_status: str
    reason: str = "Status updated via planner"


class OrderOperationProgressUpdate(BaseModel):
    completed_quantity: int = Field(..., ge=0)
    status: str | None = None
    notes: str | None = None


class OrderOperationOut(BaseModel):
    operation_id: str
    order_id: str
    operation_code: str
    sequence_number: int
    planned_duration_minutes: int
    setup_minutes: int
    labor_required: int
    tooling_id: str | None = None
    completed_quantity: int
    actual_start_time: datetime | None = None
    actual_end_time: datetime | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class OrderOut(BaseModel):
    order_id: str
    product_id: str
    routing_id: str
    quantity: int
    completed_quantity: int
    priority: int
    customer_name: str | None = None
    release_date: datetime
    due_date: datetime
    is_urgent: bool
    status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChangeoverUpsert(BaseModel):
    machine_id: str | None = None
    from_product_id: str
    to_product_id: str
    changeover_minutes: int = Field(..., ge=0)
    cleaning_required: bool = False
    notes: str | None = None


class ChangeoverOut(BaseModel):
    id: int
    machine_id: str | None = None
    from_product_id: str
    to_product_id: str
    changeover_minutes: int
    cleaning_required: bool
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)

