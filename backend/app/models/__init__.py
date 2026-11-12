"""
Exports all SQLAlchemy ORM models so Alembic and metadata utilities
automatically discover every table when importing `app.models`.
"""

from app.models.auth import Role, User, UserRole
from app.models.governance import (
    AuditLog,
    ConstraintViolation,
    GroundTruth,
    Notification,
    StateChangeEvent,
)
from app.models.master_data import (
    Operation,
    OperationMachineEligibility,
    Product,
    Routing,
    RoutingOperation,
)
from app.models.materials import InventoryLot, Material, MaterialRequirement
from app.models.orders import (
    ChangeoverMatrix,
    ProductionOrder,
    ProductionOrderOperation,
)
from app.models.resources import (
    LaborResource,
    LaborShift,
    Machine,
    MachineCalendar,
    MachineDowntime,
    SharedTooling,
)
from app.models.scheduling import OperationSchedule, SchedulingRun, ToolingAllocation

__all__ = [
    "Product",
    "Routing",
    "Operation",
    "RoutingOperation",
    "OperationMachineEligibility",
    "Machine",
    "MachineCalendar",
    "MachineDowntime",
    "LaborShift",
    "LaborResource",
    "SharedTooling",
    "Material",
    "InventoryLot",
    "MaterialRequirement",
    "ProductionOrder",
    "ProductionOrderOperation",
    "ChangeoverMatrix",
    "SchedulingRun",
    "OperationSchedule",
    "ToolingAllocation",
    "ConstraintViolation",
    "GroundTruth",
    "AuditLog",
    "StateChangeEvent",
    "Notification",
    "User",
    "Role",
    "UserRole",
]
