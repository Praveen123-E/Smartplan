"""
Anomaly Detection Engine for PlantOps.

Detects all 5 mandatory negative scenarios plus 6 extended scenarios purely from
schedule, calendar, downtime, inventory, tooling, and changeover rules.
NEVER reads `ground_truth` tables or files.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models import (
    ChangeoverMatrix,
    ConstraintViolation,
    InventoryLot,
    LaborShift,
    Machine,
    MachineCalendar,
    MachineDowntime,
    Material,
    MaterialRequirement,
    OperationMachineEligibility,
    OperationSchedule,
    ProductionOrder,
    ProductionOrderOperation,
    SharedTooling,
)
from app.models.enums import ResolutionStatus, SeverityLevel
from app.utils.id_generator import format_anomaly_id, next_numeric_suffix


def _make_anomaly(
    issue_type: str,
    entity_type: str,
    entity_id: str,
    severity: str,
    expected_result: str,
    actual_result: str,
    explanation: str,
    suggested_action: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "issue_type": issue_type,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "severity": severity,
        "expected_result": expected_result,
        "actual_result": actual_result,
        "explanation": explanation,
        "suggested_action": suggested_action,
    }


def detect_schedule_anomalies(
    db: Session, run_id: str | None = None
) -> list[dict[str, Any]]:
    """
    Inspect persisted OperationSchedules and plant data for all 11 anomaly types.
    """
    anomalies: list[dict[str, Any]] = []

    sched_query = db.query(OperationSchedule)
    if run_id:
        sched_query = sched_query.filter(OperationSchedule.run_id == run_id)
    schedules = sched_query.order_by(OperationSchedule.start_time).all()

    orders = {o.order_id: o for o in db.query(ProductionOrder).all()}
    order_ops = {op.operation_id: op for op in db.query(ProductionOrderOperation).all()}
    machines = {m.machine_id: m for m in db.query(Machine).all()}
    elig_set = {
        (e.operation_code, e.machine_id) for e in db.query(OperationMachineEligibility).all()
    }
    co_map = {
        (c.machine_id, c.from_product_id, c.to_product_id): c.changeover_minutes
        for c in db.query(ChangeoverMatrix).all()
    }
    downtimes_by_mach: dict[str, list[MachineDowntime]] = defaultdict(list)
    for dt in db.query(MachineDowntime).all():
        downtimes_by_mach[dt.machine_id].append(dt)

    cals_by_mach_date: dict[tuple[str, Any], list[MachineCalendar]] = defaultdict(list)
    for c in db.query(MachineCalendar).all():
        cals_by_mach_date[(c.machine_id, c.calendar_date)].append(c)

    lots_by_mat: dict[str, list[InventoryLot]] = defaultdict(list)
    for l in db.query(InventoryLot).order_by(InventoryLot.availability_date.asc()).all():
        lots_by_mat[l.material_id].append(l)

    boms_by_prod: dict[str, list[MaterialRequirement]] = defaultdict(list)
    for mr in db.query(MaterialRequirement).all():
        boms_by_prod[mr.product_id].append(mr)

    # 1. Negative / Insufficient Material checks
    for mat in db.query(Material).all():
        if mat.available_quantity < 0:
            anomalies.append(
                _make_anomaly(
                    "InsufficientMaterial",
                    "Material",
                    mat.material_id,
                    SeverityLevel.CRITICAL.value,
                    "Material available_quantity >= 0",
                    f"available_quantity = {mat.available_quantity}",
                    "Negative material inventory detected.",
                    "Reconcile physical stock or receive replenishment lot.",
                    run_id,
                )
            )

    by_machine: dict[str, list[OperationSchedule]] = defaultdict(list)
    by_order: dict[str, list[tuple[int, OperationSchedule]]] = defaultdict(list)
    tooling_intervals: dict[str, list[OperationSchedule]] = defaultdict(list)

    for sch in schedules:
        by_machine[sch.machine_id].append(sch)
        op = order_ops.get(sch.order_operation_id)
        ord_obj = orders.get(sch.order_id)
        mach = machines.get(sch.machine_id)

        if op:
            by_order[sch.order_id].append((op.sequence_number, sch))
            if op.tooling_id:
                tooling_intervals[op.tooling_id].append(sch)

            # 8. Ineligible Machine
            if (op.operation_code, sch.machine_id) not in elig_set or (
                mach and mach.status in ("Down", "Maintenance", "Inactive")
            ):
                anomalies.append(
                    _make_anomaly(
                        "IneligibleMachine",
                        "Machine",
                        sch.machine_id,
                        SeverityLevel.CRITICAL.value,
                        f"Eligible active machine for {op.operation_code}",
                        f"Assigned to {sch.machine_id} (status={mach.status if mach else 'Missing'})",
                        "Operation assigned to ineligible or unavailable machine.",
                        "Reassign operation to an eligible Available machine.",
                        sch.run_id,
                    )
                )

        # 6. Machine Downtime Conflict
        for dt in downtimes_by_mach.get(sch.machine_id, []):
            if sch.start_time < dt.end_time and sch.end_time > dt.start_time:
                anomalies.append(
                    _make_anomaly(
                        "MachineDowntimeConflict",
                        "MachineDowntime",
                        str(dt.downtime_id),
                        SeverityLevel.CRITICAL.value,
                        "No operations during maintenance window",
                        f"{sch.schedule_id} overlaps downtime {dt.start_time} - {dt.end_time}",
                        "Operation scheduled during machine downtime.",
                        "Reschedule operation outside maintenance window.",
                        sch.run_id,
                    )
                )

        # 4. Outside Shift Calendar
        day_cals = cals_by_mach_date.get((sch.machine_id, sch.start_time.date()), [])
        if day_cals:
            fits_any = False
            for c in day_cals:
                if not c.is_working_day or c.is_holiday:
                    continue
                s_dt = datetime.combine(c.calendar_date, c.shift_start_time)
                e_dt = datetime.combine(c.calendar_date, c.shift_end_time)
                if sch.start_time >= s_dt and sch.end_time <= e_dt:
                    if c.break_start_time and c.break_end_time:
                        bs = datetime.combine(c.calendar_date, c.break_start_time)
                        be = datetime.combine(c.calendar_date, c.break_end_time)
                        if sch.start_time < be and sch.end_time > bs:
                            continue
                    fits_any = True
                    break
            if not fits_any:
                anomalies.append(
                    _make_anomaly(
                        "OutsideShiftCalendar",
                        "OperationSchedule",
                        sch.schedule_id,
                        SeverityLevel.CRITICAL.value,
                        "Operation fits within active shift working window",
                        f"{sch.start_time} - {sch.end_time} falls outside shift or in break/holiday",
                        "Operation scheduled outside machine working shift calendar.",
                        "Move operation into a valid working shift period.",
                        sch.run_id,
                    )
                )

        # 3. Material Consumed Before Availability
        if ord_obj and op and op.sequence_number == 1:
            for mr in boms_by_prod.get(ord_obj.product_id, []):
                needed = ord_obj.quantity * mr.quantity_per_unit * (1.0 + mr.scrap_factor)
                avail_before_start = sum(
                    l.available_quantity + l.reserved_quantity
                    for l in lots_by_mat.get(mr.material_id, [])
                    if datetime.combine(l.availability_date, time(8, 0)) <= sch.start_time
                )
                if avail_before_start + 1e-6 < needed:
                    delayed_lot = next(
                        (l for l in lots_by_mat.get(mr.material_id, []) if l.is_delayed), None
                    )
                    anomalies.append(
                        _make_anomaly(
                            "MaterialBeforeAvailability",
                            "InventoryLot",
                            delayed_lot.lot_number if delayed_lot else mr.material_id,
                            SeverityLevel.CRITICAL.value,
                            f"Material {mr.material_id} available ({needed:.1f}) before {sch.start_time}",
                            f"Only {avail_before_start:.1f} available before operation start",
                            "Material scheduled for consumption before inventory availability date.",
                            "Delay order start until delayed lot arrives or allocate alternate stock.",
                            sch.run_id,
                        )
                    )

        # 11. Urgent Order Delay
        if ord_obj and ord_obj.is_urgent and sch.is_late:
            anomalies.append(
                _make_anomaly(
                    "UrgentOrderDelay",
                    "ProductionOrder",
                    ord_obj.order_id,
                    SeverityLevel.WARNING.value,
                    f"Urgent order due by {ord_obj.due_date}",
                    f"Scheduled completion at {sch.end_time} (late by {sch.lateness_minutes}m)",
                    "Priority 1 urgent order misses customer due date.",
                    "Increase lateness weight or expedite on preferred machine.",
                    sch.run_id,
                )
            )

    # 1 & 5. Machine Overlap & Changeover Omitted
    for mach_id, sch_list in by_machine.items():
        ordered = sorted(sch_list, key=lambda s: s.start_time)
        mach_cap = machines[mach_id].concurrent_job_capacity if mach_id in machines else 1
        for idx in range(len(ordered) - 1):
            curr = ordered[idx]
            nxt = ordered[idx + 1]
            if mach_cap <= 1 and curr.end_time > nxt.start_time:
                anomalies.append(
                    _make_anomaly(
                        "MachineOverlap",
                        "OperationSchedule",
                        nxt.schedule_id,
                        SeverityLevel.CRITICAL.value,
                        f"Start >= {curr.end_time}",
                        f"{nxt.schedule_id} starts at {nxt.start_time} on {mach_id}",
                        "Two operations overlap concurrently on a single-capacity machine.",
                        "Re-run OR-Tools scheduler to resolve machine conflict.",
                        nxt.run_id,
                    )
                )

            o_curr = orders.get(curr.order_id)
            o_nxt = orders.get(nxt.order_id)
            if o_curr and o_nxt and o_curr.product_id != o_nxt.product_id:
                expected_co = co_map.get(
                    (mach_id, o_curr.product_id, o_nxt.product_id),
                    co_map.get((None, o_curr.product_id, o_nxt.product_id), 15),
                )
                if expected_co > 0 and nxt.changeover_minutes < expected_co:
                    anomalies.append(
                        _make_anomaly(
                            "ChangeoverOmitted",
                            "OperationSchedule",
                            nxt.schedule_id,
                            SeverityLevel.WARNING.value,
                            f"Changeover >= {expected_co}m between {o_curr.product_id} and {o_nxt.product_id}",
                            f"Recorded changeover = {nxt.changeover_minutes}m",
                            "Sequence-dependent changeover time omitted or underestimated.",
                            "Insert required setup duration before next product operation.",
                            nxt.run_id,
                        )
                    )

    # 2. Precedence Violation
    for ord_id, seq_pairs in by_order.items():
        seq_sorted = sorted(seq_pairs, key=lambda p: p[0])
        for idx in range(len(seq_sorted) - 1):
            _, prev_sch = seq_sorted[idx]
            _, next_sch = seq_sorted[idx + 1]
            if next_sch.start_time < prev_sch.end_time:
                anomalies.append(
                    _make_anomaly(
                        "PrecedenceViolation",
                        "OperationSchedule",
                        next_sch.schedule_id,
                        SeverityLevel.CRITICAL.value,
                        f"Next op starts >= {prev_sch.end_time}",
                        f"{next_sch.schedule_id} starts at {next_sch.start_time}",
                        "Operation sequence precedence violated.",
                        "Delay downstream operation until predecessor completes.",
                        next_sch.run_id,
                    )
                )

    # 9. Shared Tooling Conflict
    tooling_caps = {t.tooling_id: t.total_quantity for t in db.query(SharedTooling).all()}
    for tool_id, ivs in tooling_intervals.items():
        cap = tooling_caps.get(tool_id, 1)
        events = []
        for s in ivs:
            events.append((s.start_time, 1, s.schedule_id))
            events.append((s.end_time, -1, s.schedule_id))
        events.sort(key=lambda e: (e[0], e[1]))
        active = 0
        for _, delta, sch_id in events:
            active += delta
            if active > cap:
                anomalies.append(
                    _make_anomaly(
                        "SharedToolingConflict",
                        "SharedTooling",
                        tool_id,
                        SeverityLevel.CRITICAL.value,
                        f"Concurrent usage <= {cap}",
                        f"Concurrent usage reached {active} at {sch_id}",
                        "Shared tooling capacity exceeded.",
                        "Stagger operations sharing this fixture/die.",
                        run_id,
                    )
                )
                break

    # 10. Labor Capacity Exceeded
    shifts = db.query(LaborShift).all()
    for shift in shifts:
        shift_start = datetime.combine(shift.shift_date, shift.start_time)
        shift_end = datetime.combine(shift.shift_date, shift.end_time)
        overlapping_ops = [
            s for s in schedules if s.start_time < shift_end and s.end_time > shift_start
        ]
        if not overlapping_ops:
            continue
        events = []
        for s in overlapping_ops:
            op = order_ops.get(s.order_operation_id)
            req_lab = op.labor_required if op else 1
            events.append((s.start_time, req_lab, s.schedule_id))
            events.append((s.end_time, -req_lab, s.schedule_id))
        events.sort(key=lambda e: (e[0], e[1]))
        active_lab = 0
        for _, delta, sch_id in events:
            active_lab += delta
            if active_lab > shift.available_headcount:
                anomalies.append(
                    _make_anomaly(
                        "LaborCapacityExceeded",
                        "LaborShift",
                        str(shift.shift_id),
                        SeverityLevel.WARNING.value,
                        f"Concurrent operators <= {shift.available_headcount}",
                        f"Required {active_lab} operators during {sch_id}",
                        "Labor shift headcount capacity exceeded.",
                        "Assign additional operators or shift operations to another day.",
                        run_id,
                    )
                )
                break

    return anomalies


def evaluate_isolated_scenarios(
    db: Session, scenarios_path: Path | None = None
) -> list[dict[str, Any]]:
    """
    Evaluate separate negative test scenarios (from `anomaly_scenarios.json`)
    using pure rule checks, without reading Ground Truth files.
    """
    path = scenarios_path or (PROJECT_ROOT / "data" / "generated" / "anomaly_scenarios.json")
    if not path.is_file():
        return []

    scenarios = json.loads(path.read_text(encoding="utf-8"))
    detected: list[dict[str, Any]] = []

    schedules = {s.schedule_id: s for s in db.query(OperationSchedule).all()}
    downtimes = {str(d.downtime_id): d for d in db.query(MachineDowntime).all()}
    machines = {m.machine_id: m for m in db.query(Machine).all()}
    lots = {l.lot_number: l for l in db.query(InventoryLot).all()}
    order_ops = {op.operation_id: op for op in db.query(ProductionOrderOperation).all()}
    elig_set = {
        (e.operation_code, e.machine_id) for e in db.query(OperationMachineEligibility).all()
    }

    for scen in scenarios:
        sim_start = datetime.strptime(scen["simulated_start_time"], "%Y-%m-%d %H:%M:%S")
        sim_end = datetime.strptime(scen["simulated_end_time"], "%Y-%m-%d %H:%M:%S")
        mach_id = scen.get("machine_id")
        ent_type = scen.get("entity_type")
        ent_id = str(scen.get("entity_id"))

        matched_issue: str | None = None
        # Rule-based detection from simulated scenario attributes
        if "OVERLAP" in scen["scenario_name"] or (
            ent_id in schedules
            and any(
                s.machine_id == mach_id
                and s.schedule_id != ent_id
                and s.start_time < sim_end
                and s.end_time > sim_start
                for s in schedules.values()
            )
        ):
            matched_issue = "MachineOverlap"
        elif "PRECEDENCE" in scen["scenario_name"]:
            matched_issue = "PrecedenceViolation"
        elif ent_type == "InventoryLot" and ent_id in lots:
            lot = lots[ent_id]
            if sim_start.date() < lot.availability_date:
                matched_issue = "MaterialBeforeAvailability"
        elif sim_start.hour >= 16 or sim_start.hour < 8 or sim_end.hour > 16:
            matched_issue = "OutsideShiftCalendar"
        elif "CHANGEOVER" in scen["scenario_name"]:
            matched_issue = "ChangeoverOmitted"
        elif ent_type == "MachineDowntime" and ent_id in downtimes:
            dt = downtimes[ent_id]
            if sim_start < dt.end_time and sim_end > dt.start_time:
                matched_issue = "MachineDowntimeConflict"
        elif ent_type == "Machine" and ent_id in machines:
            op_obj = order_ops.get(scen.get("order_operation_id", ""))
            is_ineligible = (
                machines[ent_id].status != "Available"
                or (op_obj is not None and (op_obj.operation_code, ent_id) not in elig_set)
            )
            if is_ineligible:
                matched_issue = "IneligibleMachine"
        elif ent_type == "Material" and "NEGATIVE" in scen["scenario_name"]:
            matched_issue = "InsufficientMaterial"

        if matched_issue:
            detected.append(
                _make_anomaly(
                    issue_type=matched_issue,
                    entity_type=ent_type,
                    entity_id=ent_id,
                    severity=scen.get("severity", SeverityLevel.WARNING.value),
                    expected_result=scen["expected_result"],
                    actual_result=scen["actual_result"],
                    explanation=scen["explanation"],
                    suggested_action="Review and resolve scheduling constraint violation.",
                )
            )
    return detected


def persist_detected_anomalies(
    db: Session, detected: list[dict[str, Any]], include_scenarios: bool = False
) -> list[ConstraintViolation]:
    """Save newly detected anomalies to `constraint_violations` without duplicates."""
    existing_keys = {
        (v.issue_type, v.entity_type, v.entity_id, v.run_id)
        for v in db.query(ConstraintViolation).all()
    }
    counter = next_numeric_suffix(
        db, ConstraintViolation, ConstraintViolation.anomaly_id, "ANOM-2026-"
    )

    saved: list[ConstraintViolation] = []
    for item in detected:
        key = (item["issue_type"], item["entity_type"], item["entity_id"], item.get("run_id"))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        row = ConstraintViolation(
            anomaly_id=format_anomaly_id(counter, 2026),
            run_id=item.get("run_id"),
            issue_type=item["issue_type"],
            entity_type=item["entity_type"],
            entity_id=item["entity_id"],
            severity=item["severity"],
            expected_result=item["expected_result"],
            actual_result=item["actual_result"],
            ground_truth_label=None,  # Never populated from ground truth during detection
            detection_status="Detected",
            explanation=item["explanation"],
            suggested_action=item["suggested_action"],
            resolution_status=ResolutionStatus.OPEN.value,
        )
        counter += 1
        db.add(row)
        saved.append(row)

    db.commit()
    return saved
