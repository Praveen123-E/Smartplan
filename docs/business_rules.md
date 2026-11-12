# PlantOps – Business Rules & Manufacturing Domain Logic

This document explains the core manufacturing rules enforced across the PlantOps database, FastAPI services, validation engine, OR-Tools CP-SAT scheduler, and anomaly detector.

---

## 1. Production Order Lifecycle & Valid State Transitions

Production orders follow a strict state machine (`app/utils/lifecycle.py`):

| Current State | Allowed Next States |
| :--- | :--- |
| `Draft` | `Released`, `Cancelled` |
| `Released` | `Planned`, `Scheduled`, `In Progress`, `Delayed`, `Infeasible`, `Cancelled` |
| `Planned` | `Scheduled`, `In Progress`, `Delayed`, `Infeasible`, `Cancelled` |
| `Scheduled` | `In Progress`, `Completed`, `Delayed`, `Infeasible`, `Cancelled` |
| `In Progress` | `Completed`, `Delayed`, `Cancelled` |
| `Delayed` | `Scheduled`, `In Progress`, `Completed`, `Infeasible`, `Cancelled` |
| `Infeasible` | `Planned`, `Scheduled`, `Cancelled` |
| `Completed` | *(Terminal – no further transitions)* |
| `Cancelled` | *(Terminal – no further transitions)* |

Every status transition creates an immutable row in `state_change_events` and an audit entry in `audit_logs`.

---

## 2. Business ID Conventions (Immutable & Zero-Padded)

| Entity | Format | Example |
| :--- | :--- | :--- |
| Product | `PROD-{YEAR}-{6-digit}` | `PROD-2026-000001` |
| Routing | `ROUTE-{SKU}-{2-digit}` | `ROUTE-SKU0001-01` |
| Machine | `MACH-{3-digit}` | `MACH-001` |
| Material | `MAT-{YEAR}-{6-digit}` | `MAT-2026-000001` |
| Production Order | `ORD-{YEAR}-{6-digit}` | `ORD-2026-000001` |
| Order Operation | `OP-{ORDER_ID}-{2-digit}` | `OP-ORD-2026-000001-01` |
| Operation Schedule | `SCH-{YEAR}-{6-digit}` | `SCH-2026-000001` |
| Scheduling Run | `RUN-{YEAR}-{6-digit}` | `RUN-2026-000001` |
| Constraint Violation | `ANOM-{YEAR}-{6-digit}` | `ANOM-2026-000001` |

---

## 3. Hard Scheduling Constraints (Google OR-Tools CP-SAT)

1. **Operation Sequence Precedence**: Operation `k+1` of an order cannot start until Operation `k` finishes (`end_k <= start_{k+1}`).
2. **Release Date**: Operation 1 of an order cannot start before the order's `release_date`.
3. **Material Availability Date (FIFO)**: Operations requiring materials cannot start before the earliest date when sufficient inventory lots become available.
4. **Machine Eligibility**: Each operation may only execute on machines listed in `operation_machine_eligibility` for its `operation_code`.
5. **Single-Machine Non-Overlap & Sequence-Dependent Changeover**: Implemented using `AddCircuit` with dummy node `0` so consecutive products `i -> j` on the same machine incur `changeover_matrix(m, prod_i, prod_j)` minutes between `end_i` and `start_j`.
6. **Machine Working Calendar & Downtime Exclusion**: Operations cannot span across non-working days, holidays, break periods, or planned/unplanned `machine_downtime` intervals.
7. **Shared Tooling Capacity**: Operations requiring a shared `tooling_id` satisfy `AddCumulative(..., capacity=total_quantity)`.
8. **Labor Shift Capacity**: Concurrent labor demand across active operations obeys shift `available_operators` capacity.

---

## 4. Optimization Objective

The CP-SAT solver minimizes a configurable weighted sum:

$$\text{Objective} = w_{\text{makespan}} \cdot C_{\max} + w_{\text{lateness}} \cdot \sum_{o} \text{PriorityWeight}_o \cdot \text{Tardiness}_o + w_{\text{changeover}} \cdot \sum \text{ChangeoverMinutes}$$

Where Priority 1 (Urgent) orders receive higher lateness multipliers than Priority 5 (Low) orders.

---

## 5. Inventory & Material Reservation Rules

- Stock is received into individual `inventory_lots` with explicit `availability_date` and `is_delayed` flags.
- Reservations allocate stock FIFO by `availability_date` first.
- Consuming stock updates both the lot and parent `material.available_quantity` and recalculates `stock_status` (`In Stock`, `Low Stock`, `Out of Stock`, `Delayed`).

---

## 6. Role-Based Access Control (RBAC)

| Role | Primary Permissions |
| :--- | :--- |
| `Admin` | Full system access: users, settings, master data, scheduling, exceptions, audit logs |
| `Production Planner` | Create/edit orders, products, routings, run CP-SAT scheduler, resolve exceptions |
| `Maintenance/Quality Engineer` | Manage machines, calendars, downtime, inspect & resolve exceptions |
| `Plant Operator` | View schedules, update operation progress, receive/consume inventory, report issues |

