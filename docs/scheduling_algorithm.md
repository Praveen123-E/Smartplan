# PlantOps – Scheduling Engine & Optimization Guide

## 1. Simple Step-by-Step Workflow

1. **Read Production Orders**: Load `Released`, `Planned`, or requested orders along with priorities (`1 = Urgent .. 5 = Low`), release dates, and due dates.
2. **Identify Required Operations**: Load each order's ordered `ProductionOrderOperation` steps (`OP-ORD-...-01` .. `04`).
3. **Find Eligible Machines**: Match each operation to `OperationMachineEligibility` and exclude machines in `Maintenance`, `Down`, or `Inactive` status.
4. **Build Machine Working Windows**: Convert `MachineCalendar` (working days, shifts, breaks, holidays) minus `MachineDowntime` into allowed working windows and blackout intervals.
5. **Check Material Availability**: Accumulate `InventoryLot` quantities ordered by `availability_date` to compute the earliest minute all required materials are ready.
6. **Lookup Changeovers**: Load sequence-dependent setup times from `ChangeoverMatrix` (machine-specific overrides first, then plant-wide transitions).
7. **Solve with Google OR-Tools CP-SAT**: Assign each operation to one eligible machine and start/end time while enforcing all 9 hard constraints.
8. **Save Run Independently**: Persist a new `SchedulingRun` (`RUN-YYYY-NNNNNN`) and `OperationSchedule` rows (`SCH-YYYY-NNNNNN`) without overwriting previous runs.
9. **Calculate Metrics or Explain Infeasibility**: Save makespan, total lateness, changeover time, utilization, OTD%, or a clear `infeasibility_reason`.

---

## 2. The 9 Hard Constraints

1. **Routing Precedence**: `start(op[k+1]) >= end(op[k])` for every order.
2. **Machine Eligibility**: Operations can only be assigned to eligible, active machines.
3. **Machine Capacity**: `AddNoOverlap` prevents concurrent operations on a single-capacity machine.
4. **Machine Calendar**: Non-working hours, breaks, weekends, and holidays are blocked via fixed blackout intervals in `AddNoOverlap`.
5. **Machine Downtime**: Maintenance and breakdown intervals are added as fixed blackout intervals.
6. **Sequence-Dependent Changeover**: `AddCircuit` per machine enforces `start(next) >= end(prev) + changeover(machine, prev_product, next_product)`.
7. **Labor Capacity**: `AddCumulative` ensures concurrent operations never exceed `LaborShift.available_headcount`.
8. **Material Availability**: `start(first_op) >= max(release_minute, material_ready_minute)`.
9. **Shared Tooling**: `AddCumulative` per `tooling_id` enforces `concurrent_uses <= SharedTooling.available_quantity`.

---

## 3. Objective Function (Simple Language)

We minimize a weighted penalty score:

$$\text{Objective} = w_1 \cdot \text{Makespan} + w_2 \cdot \sum_{o} (6 - \text{priority}_o) \cdot \text{Lateness}_o + w_3 \cdot \text{TotalChangeover}$$

- **Makespan**: Finish all orders as early as possible (improves throughput & machine utilization).
- **Priority-Weighted Lateness**: Finish high-priority / urgent orders (`priority = 1` gets weight `5`) before their `due_date` (improves On-Time Delivery %).
- **Total Changeover**: Group similar products on machines to minimize setup waste.

Default weights: `w1 = 1.0` (makespan), `w2 = 3.0` (lateness), `w3 = 1.5` (changeover). All weights and solver time limits are configurable per run.

---

## 4. Solver Status Distinction

- **Optimal**: CP-SAT proved mathematically that no better objective exists.
- **Feasible**: CP-SAT found a valid schedule satisfying all 9 hard constraints within the time limit, but did not prove global optimality. (Never labelled as Optimal.)
- **Infeasible**: No schedule can satisfy all hard constraints simultaneously; `infeasibility_reason` explains the bottleneck.
- **Unknown**: Time limit expired before finding any feasible solution.
- **Model Invalid**: Invalid model construction detected.

