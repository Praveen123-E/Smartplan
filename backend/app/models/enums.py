"""
Centralized domain enumerations for PlantOps.

Using standard Python `str, Enum` classes keeps database values, API validation,
and scheduling rules consistent and easy to understand.
"""

from enum import Enum


class ProductStatus(str, Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    DISCONTINUED = "Discontinued"


class MachineStatus(str, Enum):
    AVAILABLE = "Available"
    RUNNING = "Running"
    MAINTENANCE = "Maintenance"
    DOWN = "Down"
    INACTIVE = "Inactive"


class OrderStatus(str, Enum):
    DRAFT = "Draft"
    RELEASED = "Released"
    PLANNED = "Planned"
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    DELAYED = "Delayed"
    CANCELLED = "Cancelled"
    INFEASIBLE = "Infeasible"


class OperationExecutionStatus(str, Enum):
    PENDING = "Pending"
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    DELAYED = "Delayed"
    CANCELLED = "Cancelled"


class StockStatus(str, Enum):
    IN_STOCK = "In Stock"
    LOW_STOCK = "Low Stock"
    OUT_OF_STOCK = "Out of Stock"
    DELAYED = "Delayed"


class DowntimeType(str, Enum):
    PLANNED_MAINTENANCE = "Planned Maintenance"
    UNPLANNED_BREAKDOWN = "Unplanned Breakdown"
    CALIBRATION = "Calibration"


class SolverStatus(str, Enum):
    OPTIMAL = "Optimal"
    FEASIBLE = "Feasible"
    INFEASIBLE = "Infeasible"
    UNKNOWN = "Unknown"
    MODEL_INVALID = "Model Invalid"


class SeverityLevel(str, Enum):
    CRITICAL = "Critical"
    WARNING = "Warning"
    INFO = "Info"


class ResolutionStatus(str, Enum):
    OPEN = "Open"
    IN_REVIEW = "In Review"
    RESOLVED = "Resolved"
    DISMISSED = "Dismissed"


class RoleName(str, Enum):
    ADMIN = "Admin"
    PRODUCTION_PLANNER = "Production Planner"
    PLANT_OPERATOR = "Plant Operator"
    MAINTENANCE_QUALITY_ENGINEER = "Maintenance/Quality Engineer"

