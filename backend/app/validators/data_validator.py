"""
Database Validation & Data Integrity Engine for PlantOps.

Implements all 14 mandatory validation checks from Section 9:
1. Primary-key uniqueness
2. Foreign-key integrity
3. Valid business IDs
4. Allowed enums
5. Positive quantities
6. Date ordering
7. Operation sequence continuity
8. Inventory balances
9. Material requirements
10. Machine calendars
11. Lifecycle transitions
12. Duplicate records
13. Derived calculations
14. Schedule consistency
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models import (
    ChangeoverMatrix,
    InventoryLot,
    Machine,
    MachineCalendar,
    MachineDowntime,
    Material,
    MaterialRequirement,
    Operation,
    OperationMachineEligibility,
    OperationSchedule,
    Product,
    ProductionOrder,
    ProductionOrderOperation,
    Routing,
    RoutingOperation,
    SchedulingRun,
    StateChangeEvent,
)
from app.models.enums import (
    MachineStatus,
    OperationExecutionStatus,
    OrderStatus,
    ProductStatus,
    SolverStatus,
    StockStatus,
)
from app.utils.lifecycle import is_valid_order_transition


ID_PATTERNS = {
    "Product": re.compile(r"^PROD-\d{4}-\d{6}$"),
    "Routing": re.compile(r"^ROUTE-.+-\d{2}$"),
    "Machine": re.compile(r"^MACH-\d{3}$"),
    "Material": re.compile(r"^MAT-\d{4}-\d{6}$"),
    "ProductionOrder": re.compile(r"^ORD-\d{4}-\d{6}$"),
    "ProductionOrderOperation": re.compile(r"^OP-ORD-\d{4}-\d{6}-\d{2}$"),
    "OperationSchedule": re.compile(r"^SCH-\d{4}-\d{6}$"),
}


def _issue(
    check: str,
    entity_type: str,
    entity_id: str,
    message: str,
    severity: str = "Critical",
) -> dict[str, str]:
    return {
        "check": check,
        "severity": severity,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "message": message,
    }


def _check_primary_key_uniqueness(db: Session) -> list[dict[str, str]]:
    """Check logical PK uniqueness across core entities."""
    issues: list[dict[str, str]] = []
    pk_checks = [
        ("Product", db.query(Product.product_id).all()),
        ("Routing", db.query(Routing.routing_id).all()),
        ("Machine", db.query(Machine.machine_id).all()),
        ("Material", db.query(Material.material_id).all()),
        ("ProductionOrder", db.query(ProductionOrder.order_id).all()),
        ("ProductionOrderOperation", db.query(ProductionOrderOperation.operation_id).all()),
        ("OperationSchedule", db.query(OperationSchedule.schedule_id).all()),
    ]
    for entity_name, rows in pk_checks:
        seen: set[str] = set()
        for (val,) in rows:
            if val in seen:
                issues.append(_issue("pk_uniqueness", entity_name, val, f"Duplicate primary key {val}"))
            seen.add(val)
    return issues


def _check_foreign_key_integrity(db: Session) -> list[dict[str, str]]:
    """Verify all child foreign-key references point to existing parent records."""
    issues: list[dict[str, str]] = []
    product_ids = {r[0] for r in db.query(Product.product_id).all()}
    routing_ids = {r[0] for r in db.query(Routing.routing_id).all()}
    op_codes = {r[0] for r in db.query(Operation.operation_code).all()}
    machine_ids = {r[0] for r in db.query(Machine.machine_id).all()}
    material_ids = {r[0] for r in db.query(Material.material_id).all()}
    order_ids = {r[0] for r in db.query(ProductionOrder.order_id).all()}
    order_op_ids = {r[0] for r in db.query(ProductionOrderOperation.operation_id).all()}
    run_ids = {r[0] for r in db.query(SchedulingRun.run_id).all()}

    for r in db.query(Routing).all():
        if r.product_id not in product_ids:
            issues.append(_issue("fk_integrity", "Routing", r.routing_id, f"Missing product {r.product_id}"))

    for ro in db.query(RoutingOperation).all():
        if ro.routing_id not in routing_ids:
            issues.append(_issue("fk_integrity", "RoutingOperation", str(ro.id), f"Missing routing {ro.routing_id}"))
        if ro.operation_code not in op_codes:
            issues.append(_issue("fk_integrity", "RoutingOperation", str(ro.id), f"Missing operation {ro.operation_code}"))

    for o in db.query(ProductionOrder).all():
        if o.product_id not in product_ids:
            issues.append(_issue("fk_integrity", "ProductionOrder", o.order_id, f"Missing product {o.product_id}"))
        if o.routing_id not in routing_ids:
            issues.append(_issue("fk_integrity", "ProductionOrder", o.order_id, f"Missing routing {o.routing_id}"))

    for op in db.query(ProductionOrderOperation).all():
        if op.order_id not in order_ids:
            issues.append(_issue("fk_integrity", "ProductionOrderOperation", op.operation_id, f"Missing order {op.order_id}"))

    for lot in db.query(InventoryLot).all():
        if lot.material_id not in material_ids:
            issues.append(_issue("fk_integrity", "InventoryLot", lot.lot_number, f"Missing material {lot.material_id}"))

    for sch in db.query(OperationSchedule).all():
        if sch.run_id not in run_ids:
            issues.append(_issue("fk_integrity", "OperationSchedule", sch.schedule_id, f"Missing run {sch.run_id}"))
        if sch.order_id not in order_ids:
            issues.append(_issue("fk_integrity", "OperationSchedule", sch.schedule_id, f"Missing order {sch.order_id}"))
        if sch.order_operation_id not in order_op_ids:
            issues.append(_issue("fk_integrity", "OperationSchedule", sch.schedule_id, f"Missing operation {sch.order_operation_id}"))
        if sch.machine_id not in machine_ids:
            issues.append(_issue("fk_integrity", "OperationSchedule", sch.schedule_id, f"Missing machine {sch.machine_id}"))

    return issues


def _check_business_ids(db: Session) -> list[dict[str, str]]:
    """Ensure every business ID follows the PlantOps ID naming standard."""
    issues: list[dict[str, str]] = []
    targets = [
        ("Product", [r[0] for r in db.query(Product.product_id).all()]),
        ("Routing", [r[0] for r in db.query(Routing.routing_id).all()]),
        ("Machine", [r[0] for r in db.query(Machine.machine_id).all()]),
        ("Material", [r[0] for r in db.query(Material.material_id).all()]),
        ("ProductionOrder", [r[0] for r in db.query(ProductionOrder.order_id).all()]),
        ("ProductionOrderOperation", [r[0] for r in db.query(ProductionOrderOperation.operation_id).all()]),
        ("OperationSchedule", [r[0] for r in db.query(OperationSchedule.schedule_id).all()]),
    ]
    for entity_name, ids in targets:
        pattern = ID_PATTERNS[entity_name]
        for item_id in ids:
            if not pattern.match(item_id):
                issues.append(_issue("valid_ids", entity_name, item_id, f"ID '{item_id}' violates format {pattern.pattern}"))
    return issues


def _check_enums(db: Session) -> list[dict[str, str]]:
    """Check allowed status enum values across entities."""
    issues: list[dict[str, str]] = []
    valid_prod = {e.value for e in ProductStatus}
    valid_mach = {e.value for e in MachineStatus}
    valid_ord = {e.value for e in OrderStatus}
    valid_op = {e.value for e in OperationExecutionStatus}
    valid_stock = {e.value for e in StockStatus}
    valid_solver = {e.value for e in SolverStatus}

    for p in db.query(Product).all():
        if p.status not in valid_prod:
            issues.append(_issue("allowed_enums", "Product", p.product_id, f"Invalid status '{p.status}'"))
    for m in db.query(Machine).all():
        if m.status not in valid_mach:
            issues.append(_issue("allowed_enums", "Machine", m.machine_id, f"Invalid status '{m.status}'"))
    for o in db.query(ProductionOrder).all():
        if o.status not in valid_ord:
            issues.append(_issue("allowed_enums", "ProductionOrder", o.order_id, f"Invalid status '{o.status}'"))
    for op in db.query(ProductionOrderOperation).all():
        if op.status not in valid_op:
            issues.append(_issue("allowed_enums", "ProductionOrderOperation", op.operation_id, f"Invalid status '{op.status}'"))
    for mat in db.query(Material).all():
        if mat.stock_status not in valid_stock:
            issues.append(_issue("allowed_enums", "Material", mat.material_id, f"Invalid stock_status '{mat.stock_status}'"))
    for run in db.query(SchedulingRun).all():
        if run.solver_status not in valid_solver:
            issues.append(_issue("allowed_enums", "SchedulingRun", run.run_id, f"Invalid solver_status '{run.solver_status}'"))
    return issues


def _check_positive_quantities(db: Session) -> list[dict[str, str]]:
    """Verify quantities, batch sizes, capacities, and durations are positive."""
    issues: list[dict[str, str]] = []
    for p in db.query(Product).all():
        if p.standard_batch_size <= 0:
            issues.append(_issue("positive_quantities", "Product", p.product_id, "standard_batch_size must be > 0"))
    for m in db.query(Machine).all():
        if m.capacity_per_hour <= 0 or m.concurrent_job_capacity <= 0:
            issues.append(_issue("positive_quantities", "Machine", m.machine_id, "Machine capacity must be > 0"))
    for o in db.query(ProductionOrder).all():
        if o.quantity <= 0 or o.completed_quantity < 0 or o.completed_quantity > o.quantity:
            issues.append(_issue("positive_quantities", "ProductionOrder", o.order_id, "Invalid order quantity/completed_quantity"))
    for op in db.query(ProductionOrderOperation).all():
        if op.planned_duration_minutes <= 0 or op.setup_minutes < 0:
            issues.append(_issue("positive_quantities", "ProductionOrderOperation", op.operation_id, "Invalid operation duration/setup"))
    for lot in db.query(InventoryLot).all():
        if lot.initial_quantity <= 0:
            issues.append(_issue("positive_quantities", "InventoryLot", lot.lot_number, "initial_quantity must be > 0"))
    for sch in db.query(OperationSchedule).all():
        if sch.duration_minutes <= 0:
            issues.append(_issue("positive_quantities", "OperationSchedule", sch.schedule_id, "duration_minutes must be > 0"))
    return issues


def _check_date_ordering(db: Session) -> list[dict[str, str]]:
    """Verify start/end and release/due dates follow chronological order."""
    issues: list[dict[str, str]] = []
    for r in db.query(Routing).all():
        if r.effective_from and r.effective_to and r.effective_to < r.effective_from:
            issues.append(_issue("date_ordering", "Routing", r.routing_id, "effective_to < effective_from"))
    for o in db.query(ProductionOrder).all():
        if o.due_date <= o.release_date:
            issues.append(_issue("date_ordering", "ProductionOrder", o.order_id, "due_date must be after release_date"))
    for dt in db.query(MachineDowntime).all():
        if dt.end_time <= dt.start_time:
            issues.append(_issue("date_ordering", "MachineDowntime", str(dt.downtime_id), "end_time <= start_time"))
    for lot in db.query(InventoryLot).all():
        if lot.expiry_date and lot.expiry_date <= lot.availability_date:
            issues.append(_issue("date_ordering", "InventoryLot", lot.lot_number, "expiry_date <= availability_date"))
    for sch in db.query(OperationSchedule).all():
        if sch.end_time <= sch.start_time:
            issues.append(_issue("date_ordering", "OperationSchedule", sch.schedule_id, "end_time <= start_time"))
    return issues


def _check_operation_sequence(db: Session) -> list[dict[str, str]]:
    """Ensure routing operations and order operations form continuous 1..N sequences."""
    issues: list[dict[str, str]] = []

    routing_groups: dict[str, list[int]] = defaultdict(list)
    for ro in db.query(RoutingOperation).all():
        routing_groups[ro.routing_id].append(ro.sequence_number)
    for r_id, seqs in routing_groups.items():
        if sorted(seqs) != list(range(1, len(seqs) + 1)):
            issues.append(_issue("operation_sequence", "Routing", r_id, f"Non-sequential steps: {sorted(seqs)}"))

    order_groups: dict[str, list[int]] = defaultdict(list)
    for op in db.query(ProductionOrderOperation).all():
        order_groups[op.order_id].append(op.sequence_number)
    for ord_id, seqs in order_groups.items():
        if sorted(seqs) != list(range(1, len(seqs) + 1)):
            issues.append(_issue("operation_sequence", "ProductionOrder", ord_id, f"Non-sequential order steps: {sorted(seqs)}"))
    return issues


def _check_inventory_balances(db: Session) -> list[dict[str, str]]:
    """Ensure no negative inventory and material totals match lot sums."""
    issues: list[dict[str, str]] = []
    lots_by_mat: dict[str, list[InventoryLot]] = defaultdict(list)
    for lot in db.query(InventoryLot).all():
        lots_by_mat[lot.material_id].append(lot)
        if lot.available_quantity < 0 or lot.reserved_quantity < 0 or lot.consumed_quantity < 0:
            issues.append(_issue("inventory_balances", "InventoryLot", lot.lot_number, "Negative lot quantity detected"))
        accounted = lot.available_quantity + lot.reserved_quantity + lot.consumed_quantity
        if accounted > lot.initial_quantity + 1e-4:
            issues.append(_issue("inventory_balances", "InventoryLot", lot.lot_number, "Lot quantities exceed initial_quantity"))

    for mat in db.query(Material).all():
        if mat.available_quantity < 0 or mat.reserved_quantity < 0 or mat.consumed_quantity < 0:
            issues.append(_issue("inventory_balances", "Material", mat.material_id, "Negative material balance detected"))
        lot_sum = round(sum(l.available_quantity for l in lots_by_mat.get(mat.material_id, [])), 2)
        if abs(round(mat.available_quantity, 2) - lot_sum) > 0.05:
            issues.append(
                _issue(
                    "inventory_balances",
                    "Material",
                    mat.material_id,
                    f"Available quantity ({mat.available_quantity}) != sum of lots ({lot_sum})",
                )
            )
    return issues


def _check_material_requirements(db: Session) -> list[dict[str, str]]:
    """Verify BOM material requirements have positive quantity and valid scrap factor."""
    issues: list[dict[str, str]] = []
    product_ids = {r[0] for r in db.query(Product.product_id).all()}
    material_ids = {r[0] for r in db.query(Material.material_id).all()}
    for mr in db.query(MaterialRequirement).all():
        if mr.product_id not in product_ids or mr.material_id not in material_ids:
            issues.append(_issue("material_requirements", "MaterialRequirement", str(mr.id), "Broken product/material reference"))
        if mr.quantity_per_unit <= 0 or mr.scrap_factor < 0:
            issues.append(_issue("material_requirements", "MaterialRequirement", str(mr.id), "Invalid quantity_per_unit or scrap_factor"))
    return issues


def _check_machine_calendars(db: Session) -> list[dict[str, str]]:
    """Verify machine calendar shifts, holidays, and break windows."""
    issues: list[dict[str, str]] = []
    for cal in db.query(MachineCalendar).all():
        if cal.is_holiday and cal.is_working_day:
            issues.append(_issue("machine_calendars", "MachineCalendar", str(cal.calendar_id), "Holiday marked as working day"))
        if cal.shift_end_time <= cal.shift_start_time:
            issues.append(_issue("machine_calendars", "MachineCalendar", str(cal.calendar_id), "shift_end_time <= shift_start_time"))
        if cal.available_minutes < 0:
            issues.append(_issue("machine_calendars", "MachineCalendar", str(cal.calendar_id), "Negative available_minutes"))
        if cal.break_start_time and cal.break_end_time:
            if cal.break_end_time <= cal.break_start_time:
                issues.append(_issue("machine_calendars", "MachineCalendar", str(cal.calendar_id), "break_end_time <= break_start_time"))
    return issues


def _check_lifecycle_transitions(db: Session) -> list[dict[str, str]]:
    """Verify logged ProductionOrder state transitions are allowed by lifecycle rules."""
    issues: list[dict[str, str]] = []
    events = (
        db.query(StateChangeEvent)
        .filter(StateChangeEvent.entity_type == "ProductionOrder")
        .all()
    )
    for evt in events:
        if not is_valid_order_transition(evt.previous_state, evt.new_state):
            issues.append(
                _issue(
                    "lifecycle_transitions",
                    "StateChangeEvent",
                    evt.entity_id,
                    f"Invalid transition {evt.previous_state} -> {evt.new_state}",
                )
            )
    return issues


def _check_duplicate_records(db: Session) -> list[dict[str, str]]:
    """Verify unique business keys (SKU, lot_number, schedule per operation per run)."""
    issues: list[dict[str, str]] = []
    seen_skus: set[str] = set()
    for (sku,) in db.query(Product.sku).all():
        if sku in seen_skus:
            issues.append(_issue("duplicate_records", "Product", sku, f"Duplicate SKU {sku}"))
        seen_skus.add(sku)

    seen_lots: set[str] = set()
    for (lot_num,) in db.query(InventoryLot.lot_number).all():
        if lot_num in seen_lots:
            issues.append(_issue("duplicate_records", "InventoryLot", lot_num, f"Duplicate lot {lot_num}"))
        seen_lots.add(lot_num)

    seen_run_op: set[tuple[str, str]] = set()
    for sch in db.query(OperationSchedule).all():
        key = (sch.run_id, sch.order_operation_id)
        if key in seen_run_op:
            issues.append(_issue("duplicate_records", "OperationSchedule", sch.schedule_id, f"Duplicate schedule for {key}"))
        seen_run_op.add(key)
    return issues


def _check_derived_calculations(db: Session) -> list[dict[str, str]]:
    """Verify derived stock_status and schedule duration_minutes match source values."""
    issues: list[dict[str, str]] = []
    lots_by_mat: dict[str, list[InventoryLot]] = defaultdict(list)
    for lot in db.query(InventoryLot).all():
        lots_by_mat[lot.material_id].append(lot)

    for mat in db.query(Material).all():
        has_delay = any(l.is_delayed for l in lots_by_mat.get(mat.material_id, []))
        if mat.available_quantity <= 0:
            expected_status = StockStatus.OUT_OF_STOCK.value
        elif has_delay:
            expected_status = StockStatus.DELAYED.value
        elif mat.available_quantity < mat.reorder_level:
            expected_status = StockStatus.LOW_STOCK.value
        else:
            expected_status = StockStatus.IN_STOCK.value

        if mat.stock_status != expected_status:
            issues.append(
                _issue(
                    "derived_calculations",
                    "Material",
                    mat.material_id,
                    f"stock_status is '{mat.stock_status}', expected '{expected_status}'",
                    severity="Warning",
                )
            )

    for sch in db.query(OperationSchedule).all():
        calc_mins = int(round((sch.end_time - sch.start_time).total_seconds() / 60.0))
        if sch.duration_minutes != calc_mins:
            issues.append(
                _issue(
                    "derived_calculations",
                    "OperationSchedule",
                    sch.schedule_id,
                    f"duration_minutes ({sch.duration_minutes}) != (end - start) ({calc_mins})",
                )
            )
    return issues


def _check_schedule_consistency(db: Session) -> list[dict[str, str]]:
    """Verify schedule rows respect machine capacity (no overlap), precedence, eligibility, and downtime."""
    issues: list[dict[str, str]] = []
    elig_pairs = {
        (e.operation_code, e.machine_id) for e in db.query(OperationMachineEligibility).all()
    }
    order_ops = {op.operation_id: op for op in db.query(ProductionOrderOperation).all()}
    orders = {o.order_id: o for o in db.query(ProductionOrder).all()}
    downtimes_by_mach: dict[str, list[MachineDowntime]] = defaultdict(list)
    for dt in db.query(MachineDowntime).all():
        downtimes_by_mach[dt.machine_id].append(dt)

    # Group schedules per run
    runs_schedules: dict[str, list[OperationSchedule]] = defaultdict(list)
    for sch in db.query(OperationSchedule).all():
        runs_schedules[sch.run_id].append(sch)

    for run_id, sch_list in runs_schedules.items():
        # 1. Machine overlap check (including changeover window)
        by_machine: dict[str, list[OperationSchedule]] = defaultdict(list)
        by_order: dict[str, list[tuple[int, OperationSchedule]]] = defaultdict(list)

        for sch in sch_list:
            by_machine[sch.machine_id].append(sch)
            op = order_ops.get(sch.order_operation_id)
            if op:
                by_order[sch.order_id].append((op.sequence_number, sch))
                if (op.operation_code, sch.machine_id) not in elig_pairs:
                    issues.append(
                        _issue(
                            "schedule_consistency",
                            "OperationSchedule",
                            sch.schedule_id,
                            f"Machine {sch.machine_id} is not eligible for {op.operation_code}",
                        )
                    )

            # Check downtime conflict
            eff_start = sch.changeover_start_time or sch.start_time
            for dt in downtimes_by_mach.get(sch.machine_id, []):
                if eff_start < dt.end_time and sch.end_time > dt.start_time:
                    issues.append(
                        _issue(
                            "schedule_consistency",
                            "OperationSchedule",
                            sch.schedule_id,
                            f"Overlaps machine downtime {dt.downtime_id} on {sch.machine_id}",
                        )
                    )

        for mach_id, items in by_machine.items():
            ordered = sorted(items, key=lambda x: x.start_time)
            for idx in range(len(ordered) - 1):
                curr = ordered[idx]
                nxt = ordered[idx + 1]
                nxt_eff_start = nxt.changeover_start_time or nxt.start_time
                if curr.end_time > nxt_eff_start:
                    issues.append(
                        _issue(
                            "schedule_consistency",
                            "OperationSchedule",
                            nxt.schedule_id,
                            f"Overlap on {mach_id} between {curr.schedule_id} and {nxt.schedule_id}",
                        )
                    )

        # 2. Precedence check within each order
        for ord_id, seq_items in by_order.items():
            seq_sorted = sorted(seq_items, key=lambda pair: pair[0])
            for idx in range(len(seq_sorted) - 1):
                _, prev_sch = seq_sorted[idx]
                _, next_sch = seq_sorted[idx + 1]
                if next_sch.start_time < prev_sch.end_time:
                    issues.append(
                        _issue(
                            "schedule_consistency",
                            "ProductionOrder",
                            ord_id,
                            f"Precedence violated in {run_id}: {next_sch.schedule_id} starts before {prev_sch.schedule_id} ends",
                        )
                    )

    return issues


def run_validation(db: Session, write_markdown_report: bool = False) -> dict[str, Any]:
    """
    Execute all 14 PlantOps validation checks and return a structured report.
    """
    checks = [
        ("pk_uniqueness", _check_primary_key_uniqueness),
        ("fk_integrity", _check_foreign_key_integrity),
        ("valid_ids", _check_business_ids),
        ("allowed_enums", _check_enums),
        ("positive_quantities", _check_positive_quantities),
        ("date_ordering", _check_date_ordering),
        ("operation_sequence", _check_operation_sequence),
        ("inventory_balances", _check_inventory_balances),
        ("material_requirements", _check_material_requirements),
        ("machine_calendars", _check_machine_calendars),
        ("lifecycle_transitions", _check_lifecycle_transitions),
        ("duplicate_records", _check_duplicate_records),
        ("derived_calculations", _check_derived_calculations),
        ("schedule_consistency", _check_schedule_consistency),
    ]

    all_issues: list[dict[str, str]] = []
    check_summary: list[dict[str, Any]] = []

    for check_name, check_fn in checks:
        found = check_fn(db)
        all_issues.extend(found)
        check_summary.append(
            {
                "check": check_name,
                "status": "PASSED" if len(found) == 0 else "FAILED",
                "issue_count": len(found),
            }
        )

    critical_count = sum(1 for i in all_issues if i["severity"] == "Critical")
    warning_count = sum(1 for i in all_issues if i["severity"] == "Warning")

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "overall_status": "PASSED" if len(all_issues) == 0 else "FAILED",
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in check_summary if c["status"] == "PASSED"),
        "failed_checks": sum(1 for c in check_summary if c["status"] == "FAILED"),
        "total_issues": len(all_issues),
        "critical_issues": critical_count,
        "warning_issues": warning_count,
        "checks": check_summary,
        "issues": all_issues,
    }

    if write_markdown_report:
        export_validation_markdown(report, PROJECT_ROOT / "docs" / "validation_report.md")

    return report


def export_validation_markdown(report: dict[str, Any], output_path: Path) -> None:
    """Write a human-readable validation report to `docs/validation_report.md`."""
    lines = [
        "# PlantOps – Data Validation & Integrity Report",
        "",
        f"- **Generated At**: {report['generated_at']}",
        f"- **Overall Status**: `{report['overall_status']}`",
        f"- **Checks Passed**: {report['passed_checks']} / {report['total_checks']}",
        f"- **Total Issues**: {report['total_issues']} (Critical: {report['critical_issues']}, Warning: {report['warning_issues']})",
        "",
        "## Check Summary",
        "",
        "| Check Name | Status | Issue Count |",
        "| :--- | :--- | ---: |",
    ]
    for item in report["checks"]:
        lines.append(f"| `{item['check']}` | {item['status']} | {item['issue_count']} |")

    lines.append("")
    lines.append("## Detected Issues")
    lines.append("")
    if not report["issues"]:
        lines.append("No data integrity issues detected.")
    else:
        lines.append("| Check | Severity | Entity | Entity ID | Message |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for iss in report["issues"][:100]:
            lines.append(
                f"| `{iss['check']}` | {iss['severity']} | {iss['entity_type']} | `{iss['entity_id']}` | {iss['message']} |"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

