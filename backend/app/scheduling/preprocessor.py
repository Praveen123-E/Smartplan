"""
Scheduling Data Preprocessor & Infeasibility Pre-Checker for PlantOps.

Converts database tables (Orders, Operations, MachineCalendars, Downtime,
InventoryLots, LaborShifts, SharedTooling, ChangeoverMatrix) into integer-minute
intervals ready for the Google OR-Tools CP-SAT solver.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from sqlalchemy.orm import Session

from app.models import (
    ChangeoverMatrix,
    InventoryLot,
    LaborShift,
    Machine,
    MachineCalendar,
    MachineDowntime,
    MaterialRequirement,
    OperationMachineEligibility,
    ProductionOrder,
    ProductionOrderOperation,
    SharedTooling,
)
from app.models.enums import MachineStatus, OrderStatus


@dataclass
class OpTask:
    operation_id: str
    order_id: str
    product_id: str
    operation_code: str
    sequence_number: int
    duration_minutes: int
    labor_required: int
    tooling_id: str | None
    eligible_machines: list[str]
    earliest_start_minute: int


@dataclass
class OrderBundle:
    order_id: str
    product_id: str
    priority: int
    release_minute: int
    due_minute: int
    material_ready_minute: int
    operations: list[OpTask] = field(default_factory=list)


@dataclass
class SchedulingProblem:
    horizon_start: datetime
    horizon_minutes: int
    orders: list[OrderBundle]
    machines: dict[str, Machine]
    machine_blackouts: dict[str, list[tuple[int, int]]]
    machine_working_windows: dict[str, list[tuple[int, int]]]
    changeover_lookup: dict[tuple[str | None, str, str], int]
    tooling_capacities: dict[str, int]
    labor_max_capacity: int
    labor_blackouts: list[tuple[int, int, int]]  # (start_min, end_min, unavailable_headcount)
    labor_shift_lookup: list[tuple[int, int, int]]  # (start_min, end_min, shift_id)
    infeasibility_reasons: list[str] = field(default_factory=list)


def _to_minutes(dt: datetime, origin: datetime) -> int:
    return int((dt - origin).total_seconds() // 60)


def _subtract_intervals(
    windows: list[tuple[int, int]], blackouts: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Subtract blackout intervals from a list of [start, end) working windows."""
    result = list(windows)
    for b_start, b_end in blackouts:
        next_result: list[tuple[int, int]] = []
        for w_start, w_end in result:
            if b_end <= w_start or b_start >= w_end:
                next_result.append((w_start, w_end))
            else:
                if b_start > w_start:
                    next_result.append((w_start, b_start))
                if b_end < w_end:
                    next_result.append((b_end, w_end))
        result = next_result
    return [w for w in result if w[1] > w[0]]


def _invert_windows_to_blackouts(
    working_windows: list[tuple[int, int]], horizon_minutes: int
) -> list[tuple[int, int]]:
    """Return all non-working intervals inside [0, horizon_minutes)."""
    sorted_wins = sorted(working_windows)
    blackouts: list[tuple[int, int]] = []
    cursor = 0
    for w_start, w_end in sorted_wins:
        w_start_c = max(0, w_start)
        w_end_c = min(horizon_minutes, w_end)
        if w_start_c > cursor:
            blackouts.append((cursor, w_start_c))
        cursor = max(cursor, w_end_c)
    if cursor < horizon_minutes:
        blackouts.append((cursor, horizon_minutes))
    return blackouts


def build_scheduling_problem(
    db: Session,
    order_ids: list[str] | None = None,
    max_orders: int = 25,
) -> SchedulingProblem:
    """Load database records and verify basic feasibility before running OR-Tools."""
    if order_ids:
        orders = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.order_id.in_(order_ids))
            .order_by(ProductionOrder.priority.asc(), ProductionOrder.due_date.asc())
            .all()
        )
    else:
        orders = (
            db.query(ProductionOrder)
            .filter(
                ProductionOrder.status.in_(
                    [OrderStatus.RELEASED.value, OrderStatus.PLANNED.value]
                )
            )
            .order_by(ProductionOrder.priority.asc(), ProductionOrder.due_date.asc())
            .limit(max_orders)
            .all()
        )

    all_calendars = db.query(MachineCalendar).order_by(MachineCalendar.calendar_date.asc()).all()
    if all_calendars:
        min_cal_date = min(c.calendar_date for c in all_calendars)
        max_cal_date = max(c.calendar_date for c in all_calendars)
    else:
        min_cal_date = date(2026, 11, 16)
        max_cal_date = date(2026, 11, 30)

    if orders:
        min_rel_date = min(o.release_date.date() for o in orders)
        horizon_start = datetime.combine(min(min_cal_date, min_rel_date), time(0, 0))
        max_due_date = max(o.due_date.date() for o in orders)
        horizon_end = datetime.combine(
            max(max_cal_date, max_due_date) + timedelta(days=7), time(23, 59)
        )
    else:
        horizon_start = datetime.combine(min_cal_date, time(0, 0))
        horizon_end = datetime.combine(max_cal_date + timedelta(days=7), time(23, 59))

    horizon_minutes = max(1440, _to_minutes(horizon_end, horizon_start))

    # Active / Available machines
    machines_list = db.query(Machine).all()
    machines = {m.machine_id: m for m in machines_list}
    active_machine_ids = {
        m.machine_id
        for m in machines_list
        if m.status in (MachineStatus.AVAILABLE.value, MachineStatus.RUNNING.value)
    }

    # Machine Eligibility
    elig_map: dict[str, list[str]] = defaultdict(list)
    for row in db.query(OperationMachineEligibility).all():
        if row.machine_id in active_machine_ids:
            elig_map[row.operation_code].append(row.machine_id)

    # Machine Calendars & Downtime
    cals_by_mach: dict[str, list[MachineCalendar]] = defaultdict(list)
    for c in all_calendars:
        cals_by_mach[c.machine_id].append(c)

    dt_by_mach: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for dt in db.query(MachineDowntime).all():
        s_m = max(0, _to_minutes(dt.start_time, horizon_start))
        e_m = min(horizon_minutes, _to_minutes(dt.end_time, horizon_start))
        if e_m > s_m:
            dt_by_mach[dt.machine_id].append((s_m, e_m))

    machine_working_windows: dict[str, list[tuple[int, int]]] = {}
    machine_blackouts: dict[str, list[tuple[int, int]]] = {}
    for m_id in active_machine_ids:
        raw_windows: list[tuple[int, int]] = []
        m_cals = cals_by_mach.get(m_id, [])
        if m_cals:
            for c in m_cals:
                if not c.is_working_day or c.is_holiday:
                    continue
                s_dt = datetime.combine(c.calendar_date, c.shift_start_time)
                e_dt = datetime.combine(c.calendar_date, c.shift_end_time)
                if c.break_start_time and c.break_end_time:
                    bs_dt = datetime.combine(c.calendar_date, c.break_start_time)
                    be_dt = datetime.combine(c.calendar_date, c.break_end_time)
                    raw_windows.append((_to_minutes(s_dt, horizon_start), _to_minutes(bs_dt, horizon_start)))
                    raw_windows.append((_to_minutes(be_dt, horizon_start), _to_minutes(e_dt, horizon_start)))
                else:
                    raw_windows.append((_to_minutes(s_dt, horizon_start), _to_minutes(e_dt, horizon_start)))
        else:
            # Default 08:00-16:00 working window across horizon if no calendar rows exist
            total_days = max(1, horizon_minutes // 1440)
            for d_off in range(total_days):
                d_cur = horizon_start.date() + timedelta(days=d_off)
                if d_cur.strftime("%A") == "Sunday":
                    continue
                raw_windows.append((d_off * 1440 + 480, d_off * 1440 + 720))
                raw_windows.append((d_off * 1440 + 750, d_off * 1440 + 960))

        clean_windows = _subtract_intervals(raw_windows, dt_by_mach.get(m_id, []))
        machine_working_windows[m_id] = clean_windows
        machine_blackouts[m_id] = _invert_windows_to_blackouts(clean_windows, horizon_minutes)

    # Changeover lookup
    changeover_lookup: dict[tuple[str | None, str, str], int] = {}
    for row in db.query(ChangeoverMatrix).all():
        changeover_lookup[(row.machine_id, row.from_product_id, row.to_product_id)] = row.changeover_minutes

    # Shared Tooling capacities
    tooling_capacities = {
        t.tooling_id: t.available_quantity
        for t in db.query(SharedTooling).all()
    }

    # Labor Shifts
    shifts = db.query(LaborShift).order_by(LaborShift.shift_date, LaborShift.start_time).all()
    labor_max_capacity = max([s.available_headcount for s in shifts], default=40)
    labor_windows: list[tuple[int, int]] = []
    labor_blackouts: list[tuple[int, int, int]] = []
    labor_shift_lookup: list[tuple[int, int, int]] = []
    for s in shifts:
        s_min = max(0, _to_minutes(datetime.combine(s.shift_date, s.start_time), horizon_start))
        e_min = min(horizon_minutes, _to_minutes(datetime.combine(s.shift_date, s.end_time), horizon_start))
        if e_min > s_min:
            labor_windows.append((s_min, e_min))
            labor_shift_lookup.append((s_min, e_min, s.shift_id))
            if s.available_headcount < labor_max_capacity:
                labor_blackouts.append((s_min, e_min, labor_max_capacity - s.available_headcount))

    if shifts:
        for b_start, b_end in _invert_windows_to_blackouts(labor_windows, horizon_minutes):
            labor_blackouts.append((b_start, b_end, labor_max_capacity))

    # Material Inventory tracking across orders
    lots_by_mat: dict[str, list[InventoryLot]] = defaultdict(list)
    for lot in db.query(InventoryLot).order_by(InventoryLot.availability_date.asc()).all():
        lots_by_mat[lot.material_id].append(lot)

    bom_by_product: dict[str, list[MaterialRequirement]] = defaultdict(list)
    for mr in db.query(MaterialRequirement).all():
        bom_by_product[mr.product_id].append(mr)

    # Track cumulative material reservation across selected orders (FIFO by priority)
    lot_remaining: dict[int, float] = {
        lot.lot_id: float(lot.available_quantity + lot.reserved_quantity)
        for lot_list in lots_by_mat.values()
        for lot in lot_list
    }

    infeasibility_reasons: list[str] = []
    order_bundles: list[OrderBundle] = []

    if not orders:
        infeasibility_reasons.append("No Released or Planned production orders found to schedule.")

    ops_by_order: dict[str, list[ProductionOrderOperation]] = defaultdict(list)
    for op in (
        db.query(ProductionOrderOperation)
        .order_by(ProductionOrderOperation.order_id, ProductionOrderOperation.sequence_number)
        .all()
    ):
        ops_by_order[op.order_id].append(op)

    for order in orders:
        rel_min = max(0, _to_minutes(order.release_date, horizon_start))
        due_min = max(rel_min + 1, _to_minutes(order.due_date, horizon_start))

        # Check material availability & earliest ready date
        mat_ready_min = rel_min
        for mr in bom_by_product.get(order.product_id, []):
            needed = order.quantity * mr.quantity_per_unit * (1.0 + mr.scrap_factor)
            for lot in lots_by_mat.get(mr.material_id, []):
                if needed <= 1e-6:
                    break
                avail_in_lot = lot_remaining.get(lot.lot_id, 0.0)
                if avail_in_lot <= 0:
                    continue
                take = min(avail_in_lot, needed)
                lot_remaining[lot.lot_id] = avail_in_lot - take
                needed -= take
                lot_ready_dt = datetime.combine(lot.availability_date, time(8, 0))
                mat_ready_min = max(mat_ready_min, _to_minutes(lot_ready_dt, horizon_start))
            if needed > 1e-4:
                infeasibility_reasons.append(
                    f"Order {order.order_id}: Insufficient material {mr.material_id} "
                    f"(short by {round(needed, 2)} units)."
                )

        bundle = OrderBundle(
            order_id=order.order_id,
            product_id=order.product_id,
            priority=order.priority,
            release_minute=rel_min,
            due_minute=due_min,
            material_ready_minute=mat_ready_min,
        )

        order_ops = ops_by_order.get(order.order_id, [])
        if not order_ops:
            infeasibility_reasons.append(f"Order {order.order_id} has no operations.")
            continue

        for idx_op, op in enumerate(order_ops):
            eligible = elig_map.get(op.operation_code, [])
            if not eligible:
                infeasibility_reasons.append(
                    f"Operation {op.operation_id} ({op.operation_code}) has no eligible active machines."
                )
                continue

            # Check if at least one eligible machine has a continuous window >= duration
            max_win = max(
                (
                    max((w_end - w_start for w_start, w_end in machine_working_windows.get(m_id, [])), default=0)
                    for m_id in eligible
                ),
                default=0,
            )
            if op.planned_duration_minutes > max_win:
                infeasibility_reasons.append(
                    f"Operation {op.operation_id} duration ({op.planned_duration_minutes}m) exceeds "
                    f"longest continuous shift window ({max_win}m) on eligible machines."
                )

            if op.tooling_id and tooling_capacities.get(op.tooling_id, 0) < 1:
                infeasibility_reasons.append(
                    f"Operation {op.operation_id} requires tooling {op.tooling_id} with 0 available quantity."
                )

            if op.labor_required > labor_max_capacity:
                infeasibility_reasons.append(
                    f"Operation {op.operation_id} requires {op.labor_required} operators, exceeding shift capacity ({labor_max_capacity})."
                )

            earliest = max(rel_min, mat_ready_min) if idx_op == 0 else rel_min
            bundle.operations.append(
                OpTask(
                    operation_id=op.operation_id,
                    order_id=order.order_id,
                    product_id=order.product_id,
                    operation_code=op.operation_code,
                    sequence_number=op.sequence_number,
                    duration_minutes=op.planned_duration_minutes,
                    labor_required=op.labor_required,
                    tooling_id=op.tooling_id,
                    eligible_machines=eligible,
                    earliest_start_minute=earliest,
                )
            )

        order_bundles.append(bundle)

    return SchedulingProblem(
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        orders=order_bundles,
        machines=machines,
        machine_blackouts=machine_blackouts,
        machine_working_windows=machine_working_windows,
        changeover_lookup=changeover_lookup,
        tooling_capacities=tooling_capacities,
        labor_max_capacity=labor_max_capacity,
        labor_blackouts=labor_blackouts,
        labor_shift_lookup=labor_shift_lookup,
        infeasibility_reasons=infeasibility_reasons,
    )


def lookup_changeover_minutes(
    problem: SchedulingProblem,
    machine_id: str,
    from_product_id: str,
    to_product_id: str,
) -> int:
    """Return machine-specific changeover duration, or plant-wide default."""
    if from_product_id == to_product_id:
        return 0
    if (machine_id, from_product_id, to_product_id) in problem.changeover_lookup:
        return problem.changeover_lookup[(machine_id, from_product_id, to_product_id)]
    return problem.changeover_lookup.get((None, from_product_id, to_product_id), 15)

