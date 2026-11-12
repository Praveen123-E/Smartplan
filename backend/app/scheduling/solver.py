"""
Google OR-Tools CP-SAT Production Scheduling Engine for PlantOps.

Enforces all 9 hard manufacturing constraints:
1. Routing precedence
2. Machine eligibility
3. Machine capacity
4. Machine working calendar (shifts, breaks, weekends, holidays)
5. Machine downtime avoidance
6. Sequence-dependent changeover times (ChangeoverMatrix)
7. Labor shift capacity
8. Material availability earliest-start dates
9. Shared tooling capacity
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time as time_mod
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    OperationSchedule,
    ProductionOrder,
    ProductionOrderOperation,
    SchedulingRun,
    ToolingAllocation,
)
from app.models.enums import OperationExecutionStatus, OrderStatus, SolverStatus
from app.scheduling.preprocessor import (
    SchedulingProblem,
    build_scheduling_problem,
    lookup_changeover_minutes,
)
from app.schemas.scheduling import SchedulingRunRequest
from app.services.audit_service import record_audit_log, record_state_change
from app.utils.id_generator import (
    format_run_id,
    format_schedule_id,
    next_numeric_suffix,
)


def _load_cp_model():
    """Import OR-Tools CP-SAT lazily so module import works even before `pip install ortools`."""
    try:
        from ortools.sat.python import cp_model
        return cp_model
    except ImportError as exc:
        raise RuntimeError(
            "Google OR-Tools (`ortools`) is not installed. "
            "Install it with: pip install ortools"
        ) from exc


def _map_solver_status(cp_model_mod, status_code: int) -> str:
    if status_code == cp_model_mod.OPTIMAL:
        return SolverStatus.OPTIMAL.value
    if status_code == cp_model_mod.FEASIBLE:
        return SolverStatus.FEASIBLE.value
    if status_code == cp_model_mod.INFEASIBLE:
        return SolverStatus.INFEASIBLE.value
    if status_code == cp_model_mod.MODEL_INVALID:
        return SolverStatus.MODEL_INVALID.value
    return SolverStatus.UNKNOWN.value


def _find_matching_shift_id(problem: SchedulingProblem, start_min: int, end_min: int) -> int | None:
    for s_min, e_min, shift_id in problem.labor_shift_lookup:
        if start_min >= s_min and end_min <= e_min:
            return shift_id
    return None


def _save_infeasible_run(
    db: Session,
    run_id: str,
    request: SchedulingRunRequest,
    started_at: datetime,
    exec_seconds: float,
    reasons: list[str],
    order_ids: list[str],
    unscheduled_ops_count: int,
    triggered_by: str,
    solver_status_label: str = SolverStatus.INFEASIBLE.value,
) -> SchedulingRun:
    reason_text = " | ".join(reasons) if reasons else "No feasible schedule satisfies all hard constraints."
    run = SchedulingRun(
        run_id=run_id,
        run_name=request.run_name,
        solver_status=solver_status_label,
        objective_value=None,
        best_bound=None,
        execution_duration_seconds=round(exec_seconds, 3),
        makespan_minutes=0,
        total_lateness_minutes=0,
        total_changeover_minutes=0,
        delayed_order_count=0,
        unscheduled_operation_count=unscheduled_ops_count,
        on_time_delivery_pct=0.0,
        avg_machine_utilization_pct=0.0,
        weight_makespan=request.weight_makespan,
        weight_lateness=request.weight_lateness,
        weight_changeover=request.weight_changeover,
        solver_time_limit_seconds=request.solver_time_limit_seconds,
        infeasibility_reason=reason_text,
        triggered_by=triggered_by,
        is_baseline=False,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(run)

    # Mark impacted orders Infeasible if solver confirmed Infeasible
    if solver_status_label == SolverStatus.INFEASIBLE.value:
        for oid in order_ids:
            ord_obj = db.query(ProductionOrder).filter(ProductionOrder.order_id == oid).first()
            if ord_obj and ord_obj.status not in (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value):
                prev = ord_obj.status
                ord_obj.status = OrderStatus.INFEASIBLE.value
                record_state_change(
                    db,
                    entity_type="ProductionOrder",
                    entity_id=oid,
                    previous_state=prev,
                    new_state=OrderStatus.INFEASIBLE.value,
                    changed_by=triggered_by,
                    reason=reason_text[:250],
                )

    record_audit_log(
        db,
        username=triggered_by,
        action="RUN_SCHEDULER_INFEASIBLE",
        entity_type="SchedulingRun",
        entity_id=run_id,
        new_value={"status": solver_status_label, "reason": reason_text},
    )
    db.commit()
    db.refresh(run)
    return run


def run_production_scheduling(
    db: Session,
    request: SchedulingRunRequest,
    triggered_by: str = "planner",
) -> SchedulingRun:
    """
    Build and solve the PlantOps CP-SAT scheduling optimization model,
    then persist the SchedulingRun and OperationSchedule records.
    """
    cp_model = _load_cp_model()
    wall_start = time_mod.perf_counter()
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    run_counter = next_numeric_suffix(db, SchedulingRun, SchedulingRun.run_id, "RUN-2026-")
    run_id = format_run_id(run_counter, 2026)

    problem = build_scheduling_problem(
        db=db,
        order_ids=request.order_ids,
        max_orders=request.max_orders,
    )
    all_ops = [op for ob in problem.orders for op in ob.operations]
    target_order_ids = [ob.order_id for ob in problem.orders]

    # Pre-check infeasibility before invoking CP-SAT
    if problem.infeasibility_reasons:
        return _save_infeasible_run(
            db=db,
            run_id=run_id,
            request=request,
            started_at=started_at,
            exec_seconds=time_mod.perf_counter() - wall_start,
            reasons=problem.infeasibility_reasons,
            order_ids=target_order_ids,
            unscheduled_ops_count=len(all_ops),
            triggered_by=triggered_by,
        )

    model = cp_model.CpModel()
    horizon = problem.horizon_minutes

    start_vars: dict[str, Any] = {}
    end_vars: dict[str, Any] = {}
    main_intervals: dict[str, Any] = {}
    assign_vars: dict[tuple[str, str], Any] = {}
    machine_intervals: dict[str, list[Any]] = {m_id: [] for m_id in problem.machine_blackouts}
    machine_candidate_ops: dict[str, list[Any]] = {m_id: [] for m_id in problem.machine_blackouts}
    changeover_vars: dict[str, Any] = {}

    # 1. Decision Variables per Operation
    for op in all_ops:
        lb = min(op.earliest_start_minute, max(0, horizon - op.duration_minutes))
        ub_start = max(lb, horizon - op.duration_minutes)
        s_var = model.NewIntVar(lb, ub_start, f"s_{op.operation_id}")
        e_var = model.NewIntVar(lb + op.duration_minutes, horizon, f"e_{op.operation_id}")
        iv_var = model.NewIntervalVar(s_var, op.duration_minutes, e_var, f"iv_{op.operation_id}")

        start_vars[op.operation_id] = s_var
        end_vars[op.operation_id] = e_var
        main_intervals[op.operation_id] = iv_var
        changeover_vars[op.operation_id] = model.NewIntVar(0, 120, f"co_{op.operation_id}")

        # 2. Machine Eligibility: assign to exactly 1 eligible machine
        op_assigns = []
        for m_id in op.eligible_machines:
            b_var = model.NewBoolVar(f"assign_{op.operation_id}_{m_id}")
            opt_iv = model.NewOptionalIntervalVar(
                s_var, op.duration_minutes, e_var, b_var, f"opt_{op.operation_id}_{m_id}"
            )
            assign_vars[(op.operation_id, m_id)] = b_var
            machine_intervals[m_id].append(opt_iv)
            machine_candidate_ops[m_id].append(op)
            op_assigns.append(b_var)
        model.AddExactlyOne(op_assigns)

    # 3. Routing Precedence Constraints
    for ob in problem.orders:
        for idx in range(len(ob.operations) - 1):
            op_prev = ob.operations[idx]
            op_next = ob.operations[idx + 1]
            model.Add(start_vars[op_next.operation_id] >= end_vars[op_prev.operation_id])

    # 4 & 5. Machine Capacity + Calendars + Downtime via Fixed Blackouts + NoOverlap
    for m_id, blackouts in problem.machine_blackouts.items():
        intervals_for_m = list(machine_intervals[m_id])
        for b_idx, (b_start, b_end) in enumerate(blackouts):
            if b_end > b_start:
                intervals_for_m.append(
                    model.NewFixedSizeIntervalVar(b_start, b_end - b_start, f"blk_{m_id}_{b_idx}")
                )
        if intervals_for_m:
            mach_cap = problem.machines[m_id].concurrent_job_capacity
            if mach_cap <= 1:
                model.AddNoOverlap(intervals_for_m)
            else:
                # Non-overlapping with blackouts still applies per blackout
                demands = [1] * len(machine_intervals[m_id]) + [mach_cap] * (
                    len(intervals_for_m) - len(machine_intervals[m_id])
                )
                model.AddCumulative(intervals_for_m, demands, mach_cap)

    # 6. Sequence-Dependent Changeovers via AddCircuit per Machine
    for m_id, cand_ops in machine_candidate_ops.items():
        if not cand_ops:
            continue
        k = len(cand_ops)
        depot_used = model.NewBoolVar(f"depot_{m_id}")
        arcs: list[tuple[int, int, Any]] = [(0, 0, depot_used.Not())]

        for i, op_i in enumerate(cand_ops, start=1):
            a_i = assign_vars[(op_i.operation_id, m_id)]
            model.AddImplication(a_i, depot_used)
            # Self-loop when op_i is NOT assigned to machine m_id
            arcs.append((i, i, a_i.Not()))

            # Depot -> op_i (first operation on machine has 0 setup changeover)
            lit_0_i = model.NewBoolVar(f"arc_{m_id}_0_{i}")
            arcs.append((0, i, lit_0_i))
            model.AddImplication(lit_0_i, a_i)
            model.AddImplication(lit_0_i, depot_used)
            model.Add(changeover_vars[op_i.operation_id] == 0).OnlyEnforceIf(lit_0_i)

            # op_i -> Depot
            lit_i_0 = model.NewBoolVar(f"arc_{m_id}_{i}_0")
            arcs.append((i, 0, lit_i_0))
            model.AddImplication(lit_i_0, a_i)
            model.AddImplication(lit_i_0, depot_used)

            # op_i -> op_j transitions
            for j, op_j in enumerate(cand_ops, start=1):
                if i == j:
                    continue
                a_j = assign_vars[(op_j.operation_id, m_id)]
                lit_i_j = model.NewBoolVar(f"arc_{m_id}_{i}_{j}")
                arcs.append((i, j, lit_i_j))
                model.AddImplication(lit_i_j, a_i)
                model.AddImplication(lit_i_j, a_j)
                co_mins = lookup_changeover_minutes(
                    problem, m_id, op_i.product_id, op_j.product_id
                )
                model.Add(
                    start_vars[op_j.operation_id] >= end_vars[op_i.operation_id] + co_mins
                ).OnlyEnforceIf(lit_i_j)
                model.Add(changeover_vars[op_j.operation_id] == co_mins).OnlyEnforceIf(lit_i_j)

        model.Add(sum(assign_vars[(op.operation_id, m_id)] for op in cand_ops) >= 1).OnlyEnforceIf(
            depot_used
        )
        model.AddCircuit(arcs)

    # 7. Labor Shift Capacity (Cumulative)
    if problem.labor_max_capacity > 0 and all_ops:
        labor_ivs = [main_intervals[op.operation_id] for op in all_ops]
        labor_demands = [op.labor_required for op in all_ops]
        for b_idx, (b_start, b_end, unavail) in enumerate(problem.labor_blackouts):
            if b_end > b_start and unavail > 0:
                labor_ivs.append(
                    model.NewFixedSizeIntervalVar(b_start, b_end - b_start, f"lab_blk_{b_idx}")
                )
                labor_demands.append(unavail)
        model.AddCumulative(labor_ivs, labor_demands, problem.labor_max_capacity)

    # 9. Shared Tooling Capacity (Cumulative per tool)
    ops_by_tool: dict[str, list[Any]] = {}
    for op in all_ops:
        if op.tooling_id:
            ops_by_tool.setdefault(op.tooling_id, []).append(main_intervals[op.operation_id])
    for tool_id, tool_ivs in ops_by_tool.items():
        cap = problem.tooling_capacities.get(tool_id, 1)
        model.AddCumulative(tool_ivs, [1] * len(tool_ivs), cap)

    # Objective: Minimize weighted Makespan + Priority-Weighted Lateness + Changeover
    makespan_var = model.NewIntVar(0, horizon, "makespan")
    order_end_vars = [end_vars[ob.operations[-1].operation_id] for ob in problem.orders if ob.operations]
    if order_end_vars:
        model.AddMaxEquality(makespan_var, order_end_vars)

    lateness_terms = []
    for ob in problem.orders:
        if not ob.operations:
            continue
        last_op = ob.operations[-1]
        late_var = model.NewIntVar(0, horizon, f"late_{ob.order_id}")
        model.AddMaxEquality(late_var, [0, end_vars[last_op.operation_id] - ob.due_minute])
        priority_boost = max(1, 6 - ob.priority)
        lateness_terms.append(late_var * priority_boost)

    w_mk = int(round(request.weight_makespan * 10))
    w_lt = int(round(request.weight_lateness * 10))
    w_co = int(round(request.weight_changeover * 10))

    total_co_expr = sum(changeover_vars.values()) if changeover_vars else 0
    total_late_expr = sum(lateness_terms) if lateness_terms else 0
    model.Minimize(w_mk * makespan_var + w_lt * total_late_expr + w_co * total_co_expr)

    # Solve with configurable time limit
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(request.solver_time_limit_seconds)
    solver.parameters.num_search_workers = 4
    status_code = solver.Solve(model)
    exec_seconds = time_mod.perf_counter() - wall_start
    status_label = _map_solver_status(cp_model, status_code)

    if status_label not in (SolverStatus.OPTIMAL.value, SolverStatus.FEASIBLE.value):
        diag = (
            f"OR-Tools CP-SAT returned '{status_label}'. "
            "Check shift capacities, tooling limits, or increase planning horizon."
        )
        return _save_infeasible_run(
            db=db,
            run_id=run_id,
            request=request,
            started_at=started_at,
            exec_seconds=exec_seconds,
            reasons=[diag],
            order_ids=target_order_ids,
            unscheduled_ops_count=len(all_ops),
            triggered_by=triggered_by,
            solver_status_label=status_label,
        )

    # Extract Solution & Persist Schedule
    sch_counter = next_numeric_suffix(
        db, OperationSchedule, OperationSchedule.schedule_id, "SCH-2026-"
    )

    total_co_mins = 0
    total_late_mins = 0
    delayed_orders = 0
    total_scheduled_op_mins = 0
    latest_end_dt = problem.horizon_start

    for ob in problem.orders:
        order_late = False
        order_lateness = 0
        for op in ob.operations:
            chosen_m = next(
                m_id for m_id in op.eligible_machines if solver.Value(assign_vars[(op.operation_id, m_id)]) == 1
            )
            s_min = solver.Value(start_vars[op.operation_id])
            e_min = solver.Value(end_vars[op.operation_id])
            co_mins = solver.Value(changeover_vars[op.operation_id])

            op_start_dt = problem.horizon_start + timedelta(minutes=s_min)
            op_end_dt = problem.horizon_start + timedelta(minutes=e_min)
            co_start_dt = (
                op_start_dt - timedelta(minutes=co_mins) if co_mins > 0 else None
            )
            latest_end_dt = max(latest_end_dt, op_end_dt)

            op_late_mins = max(0, e_min - ob.due_minute)
            if op_late_mins > 0:
                order_late = True
                order_lateness = max(order_lateness, op_late_mins)

            sch_id = format_schedule_id(sch_counter, 2026)
            sch_counter += 1
            total_co_mins += co_mins
            total_scheduled_op_mins += op.duration_minutes

            shift_id = _find_matching_shift_id(problem, s_min, e_min)
            sch_row = OperationSchedule(
                schedule_id=sch_id,
                run_id=run_id,
                order_id=ob.order_id,
                order_operation_id=op.operation_id,
                machine_id=chosen_m,
                labor_shift_id=shift_id,
                start_time=op_start_dt,
                end_time=op_end_dt,
                duration_minutes=op.duration_minutes,
                changeover_minutes=co_mins,
                changeover_start_time=co_start_dt,
                is_late=op_late_mins > 0,
                lateness_minutes=op_late_mins,
                status="Scheduled",
            )
            db.add(sch_row)

            if op.tooling_id:
                db.add(
                    ToolingAllocation(
                        schedule_id=sch_id,
                        tooling_id=op.tooling_id,
                        allocated_quantity=1,
                        start_time=op_start_dt,
                        end_time=op_end_dt,
                    )
                )

            op_model = (
                db.query(ProductionOrderOperation)
                .filter(ProductionOrderOperation.operation_id == op.operation_id)
                .first()
            )
            if op_model:
                op_model.status = OperationExecutionStatus.SCHEDULED.value

        ord_model = db.query(ProductionOrder).filter(ProductionOrder.order_id == ob.order_id).first()
        if ord_model:
            prev_state = ord_model.status
            new_state = OrderStatus.DELAYED.value if order_late else OrderStatus.SCHEDULED.value
            ord_model.status = new_state
            if prev_state != new_state:
                record_state_change(
                    db,
                    entity_type="ProductionOrder",
                    entity_id=ob.order_id,
                    previous_state=prev_state,
                    new_state=new_state,
                    changed_by=triggered_by,
                    reason=f"Scheduled by {run_id}",
                )

        if order_late:
            delayed_orders += 1
            total_late_mins += order_lateness

    earliest_start_min = min(
        (solver.Value(start_vars[op.operation_id]) for op in all_ops), default=0
    )
    makespan_mins = max(
        0, solver.Value(makespan_var) - earliest_start_min
    )
    total_avail_cal_mins = sum(
        (w_end - w_start)
        for windows in problem.machine_working_windows.values()
        for w_start, w_end in windows
    )
    avg_util_pct = (
        round((total_scheduled_op_mins / total_avail_cal_mins) * 100.0, 2)
        if total_avail_cal_mins > 0
        else 0.0
    )
    otd_pct = (
        round(((len(problem.orders) - delayed_orders) / len(problem.orders)) * 100.0, 2)
        if problem.orders
        else 100.0
    )

    run = SchedulingRun(
        run_id=run_id,
        run_name=request.run_name,
        solver_status=status_label,
        objective_value=round(float(solver.ObjectiveValue()), 2),
        best_bound=round(float(solver.BestObjectiveBound()), 2),
        execution_duration_seconds=round(exec_seconds, 3),
        makespan_minutes=makespan_mins,
        total_lateness_minutes=total_late_mins,
        total_changeover_minutes=total_co_mins,
        delayed_order_count=delayed_orders,
        unscheduled_operation_count=0,
        on_time_delivery_pct=otd_pct,
        avg_machine_utilization_pct=avg_util_pct,
        weight_makespan=request.weight_makespan,
        weight_lateness=request.weight_lateness,
        weight_changeover=request.weight_changeover,
        solver_time_limit_seconds=request.solver_time_limit_seconds,
        infeasibility_reason=None,
        triggered_by=triggered_by,
        is_baseline=False,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(run)
    record_audit_log(
        db,
        username=triggered_by,
        action="RUN_SCHEDULER",
        entity_type="SchedulingRun",
        entity_id=run_id,
        new_value={
            "solver_status": status_label,
            "orders": len(problem.orders),
            "makespan_minutes": makespan_mins,
            "otd_pct": otd_pct,
        },
    )
    db.commit()
    db.refresh(run)
    return run

