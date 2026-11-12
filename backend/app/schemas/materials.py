"""Pydantic schemas for Materials, Inventory Lots, and Stock Transactions."""

from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class MaterialCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    category: str = Field(..., min_length=2, max_length=80)
    unit: str = Field("kg", max_length=20)
    unit_cost: float = Field(10.0, ge=0)
    reorder_level: float = Field(50.0, ge=0)


class MaterialUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    unit_cost: float | None = Field(None, ge=0)
    reorder_level: float | None = Field(None, ge=0)
    status: str | None = None


class MaterialOut(BaseModel):
    material_id: str
    name: str
    category: str
    unit: str
    unit_cost: float
    reorder_level: float
    available_quantity: float
    reserved_quantity: float
    consumed_quantity: float
    stock_status: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryLotCreate(BaseModel):
    material_id: str
    lot_number: str = Field(..., min_length=3, max_length=64)
    quantity: float = Field(..., gt=0)
    availability_date: date
    expiry_date: date | None = None
    supplier_name: str | None = None
    is_delayed: bool = False


class InventoryActionRequest(BaseModel):
    material_id: str
    lot_id: int | None = None
    quantity: float = Field(..., gt=0)
    reason: str = "Production floor transaction"


class InventoryLotOut(BaseModel):
    lot_id: int
    material_id: str
    lot_number: str
    initial_quantity: float
    available_quantity: float
    reserved_quantity: float
    consumed_quantity: float
    availability_date: date
    expiry_date: date | None = None
    supplier_name: str | None = None
    is_delayed: bool
    status: str

    model_config = ConfigDict(from_attributes=True)

