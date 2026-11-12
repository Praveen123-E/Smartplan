"""Pydantic schemas for Products, Routings, Operations, and Machine Eligibility."""

from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class RoutingStepIn(BaseModel):
    operation_code: str = Field(..., min_length=2, max_length=32)
    sequence_number: int = Field(..., ge=1)
    duration_per_unit_minutes: float = Field(..., gt=0)
    setup_minutes: int = Field(10, ge=0)
    labor_required: int = Field(1, ge=1)
    tooling_id: str | None = None


class RoutingStepOut(RoutingStepIn):
    id: int
    routing_id: str
    operation_name: str | None = None
    operation_type: str | None = None
    eligible_machines: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class RoutingCreate(BaseModel):
    product_id: str
    version: str = Field("01", min_length=2, max_length=16)
    name: str = Field(..., min_length=2, max_length=150)
    effective_from: date | None = None
    effective_to: date | None = None
    steps: list[RoutingStepIn] = Field(..., min_length=1)


class RoutingOut(BaseModel):
    routing_id: str
    product_id: str
    version: str
    name: str
    is_active: bool
    effective_from: date | None = None
    effective_to: date | None = None
    status: str
    steps: list[RoutingStepOut] = []

    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=2, max_length=40)
    name: str = Field(..., min_length=2, max_length=150)
    category: str = Field(..., min_length=2, max_length=80)
    unit_of_measure: str = Field("pcs", max_length=20)
    standard_batch_size: int = Field(10, gt=0)
    description: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    category: str | None = None
    unit_of_measure: str | None = None
    standard_batch_size: int | None = Field(None, gt=0)
    description: str | None = None
    status: str | None = None


class ProductOut(BaseModel):
    product_id: str
    sku: str
    name: str
    category: str
    unit_of_measure: str
    standard_batch_size: int
    description: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperationOut(BaseModel):
    operation_code: str
    name: str
    operation_type: str
    description: str | None = None
    default_setup_minutes: int
    default_run_minutes_per_unit: float
    required_labor_count: int
    tooling_id: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class MaterialRequirementCreate(BaseModel):
    product_id: str
    operation_code: str | None = None
    material_id: str
    quantity_per_unit: float = Field(..., gt=0)
    scrap_factor: float = Field(0.0, ge=0)

