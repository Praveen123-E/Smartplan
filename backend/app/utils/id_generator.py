"""
Immutable business ID formatters for PlantOps.

Centralizing ID formatting ensures every module (data generator, CRUD services,
and scheduling engine) follows the exact zero-padded PlantOps ID conventions.
"""

from sqlalchemy.orm import Session


def format_product_id(counter: int, year: int = 2026) -> str:
    return f"PROD-{year}-{counter:06d}"


def format_routing_id(sku: str, version: str = "01") -> str:
    return f"ROUTE-{sku}-{version}"


def format_order_id(counter: int, year: int = 2026) -> str:
    return f"ORD-{year}-{counter:06d}"


def format_order_operation_id(order_id: str, sequence_number: int) -> str:
    return f"OP-{order_id}-{sequence_number:02d}"


def format_machine_id(counter: int) -> str:
    return f"MACH-{counter:03d}"


def format_material_id(counter: int, year: int = 2026) -> str:
    return f"MAT-{year}-{counter:06d}"


def format_schedule_id(counter: int, year: int = 2026) -> str:
    return f"SCH-{year}-{counter:06d}"


def format_run_id(counter: int, year: int = 2026) -> str:
    return f"RUN-{year}-{counter:06d}"


def format_anomaly_id(counter: int, year: int = 2026) -> str:
    return f"ANOM-{year}-{counter:06d}"


def format_tooling_id(counter: int) -> str:
    return f"TOOL-{counter:03d}"


def next_numeric_suffix(db: Session, model_cls, pk_column, prefix: str) -> int:
    """
    Find the next unused integer counter for a given business-ID prefix.
    Never reuses existing IDs even if earlier rows are inactive or cancelled.
    """
    rows = db.query(pk_column).filter(pk_column.like(f"{prefix}%")).all()
    max_num = 0
    for (value,) in rows:
        tail = value.replace(prefix, "")
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    return max_num + 1

