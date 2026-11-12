# PlantOps – Database Schema & Relationship Documentation

**Database Name**: `plantops_db` (MySQL 8.0, `utf8mb4_unicode_ci`)  
**ORM / Migrations**: SQLAlchemy 2.0 + Alembic

---

## 1. Entity Inventory (28 Tables)

### Mandatory Core Entities (10)
1. `products` (`Product`) – Manufactured SKUs (`PROD-2026-000001`).
2. `routings` (`Routing`) – Versioned manufacturing process plans (`ROUTE-{sku}-01`).
3. `operations` (`Operation`) – Master operation catalog (`OP-STD-001`).
4. `machines` (`Machine`) – Factory machine assets (`MACH-001`).
5. `machine_calendars` (`MachineCalendar`) – Daily shift windows, breaks, and holidays per machine.
6. `materials` (`Material`) – Raw materials and components (`MAT-2026-000001`).
7. `inventory_lots` (`InventoryLot`) – Stock batches with availability dates.
8. `production_orders` (`ProductionOrder`) – Customer/plant orders (`ORD-2026-000001`).
9. `operation_schedules` (`OperationSchedule`) – Solver-assigned machine schedule blocks (`SCH-2026-000001`).
10. `changeover_matrix` (`ChangeoverMatrix`) – Sequence-dependent setup times between products.

### Supporting Entities (18)
11. `routing_operations` (`RoutingOperation`) – Ordered steps inside a `Routing`.
12. `operation_machine_eligibility` (`OperationMachineEligibility`) – Eligible machines per operation.
13. `production_order_operations` (`ProductionOrderOperation`) – Order-specific operations (`OP-{order-id}-01`).
14. `material_requirements` (`MaterialRequirement`) – Bill-of-materials quantities per product/operation.
15. `labor_shifts` (`LaborShift`) – Plant-wide shift labor capacity.
16. `labor_resources` (`LaborResource`) – Operators assigned to labor shifts.
17. `machine_downtime` (`MachineDowntime`) – Planned maintenance and breakdown windows.
18. `shared_tooling` (`SharedTooling`) – Limited fixtures, jigs, and dies.
19. `tooling_allocations` (`ToolingAllocation`) – Tooling reservations tied to `OperationSchedule`.
20. `scheduling_runs` (`SchedulingRun`) – Independent solver execution snapshots (`RUN-2026-000001`).
21. `constraint_violations` (`ConstraintViolation`) – Detected anomalies and exceptions (`ANOM-2026-000001`).
22. `ground_truth` (`GroundTruth`) – Isolated evaluation labels (never used as solver input).
23. `audit_logs` (`AuditLog`) – Immutable audit history of user/system actions.
24. `state_change_events` (`StateChangeEvent`) – Explicit lifecycle transition history.
25. `users` (`User`) – System user accounts.
26. `roles` (`Role`) – RBAC role definitions.
27. `user_roles` (`UserRole`) – User-to-role assignments.
28. `notifications` (`Notification`) – User alerts and notifications.

---

## 2. Entity Relationships

### One-to-Many (1:N)
- `Product` → `Routing` (a product can have multiple versioned routings).
- `Routing` → `RoutingOperation` (ordered steps 1..N).
- `Operation` → `RoutingOperation` & `ProductionOrderOperation`.
- `Product` → `ProductionOrder` (many orders for one SKU).
- `ProductionOrder` → `ProductionOrderOperation` (each order expands into its sequence of `OP-{order-id}-NN` steps).
- `Machine` → `MachineCalendar` & `MachineDowntime` & `OperationSchedule`.
- `Material` → `InventoryLot` (a material arrives in multiple dated batches/lots).
- `LaborShift` → `LaborResource` (multiple operators assigned to one shift).
- `SchedulingRun` → `OperationSchedule` (every solver run stores its own independent set of schedule rows).
- `OperationSchedule` → `ToolingAllocation`.

### Many-to-Many (N:M via Bridge Tables)
- `Operation` ↔ `Machine` via `operation_machine_eligibility` (stores `efficiency_factor`, `is_preferred`).
- `Product` ↔ `Material` via `material_requirements` (stores `quantity_per_unit`, `scrap_factor`).
- `User` ↔ `Role` via `user_roles`.
- `Product` ↔ `Product` (transition pairs) via `changeover_matrix` (optionally scoped per `Machine`).

### Optional Relationships
- `Operation.tooling_id` / `RoutingOperation.tooling_id` / `ProductionOrderOperation.tooling_id` → `SharedTooling` (not every operation requires shared tooling).
- `ChangeoverMatrix.machine_id` → `Machine` (`NULL` represents a plant-wide default changeover time).
- `MaterialRequirement.operation_code` → `Operation` (`NULL` means material is required at order start).
- `OperationSchedule.labor_shift_id` → `LaborShift` (nullable reference to matched shift).
- `ConstraintViolation.run_id` → `SchedulingRun` (data-level anomalies can exist outside a run).
- `AuditLog.user_id` & `Notification.user_id` → `User` (`NULL` for system-generated events or global alerts).

### One-to-One (Logical 1:1 per Run)
- Within a single `SchedulingRun`, each `ProductionOrderOperation` maps to at most one `OperationSchedule` row (enforced by solver assignment logic and validated by the validation engine).

---

## 3. Effective Dates & Lifecycle Transitions

### Effective Dates
- `Routing.effective_from` and `Routing.effective_to`: Control which routing version is active for new production orders on a given date.
- `InventoryLot.availability_date` and `InventoryLot.expiry_date`: Determine when material stock becomes usable by the scheduler and flag delayed deliveries.
- `MachineCalendar.calendar_date` and `MachineDowntime.start_time`/`end_time`: Define exact working windows and blackout intervals.

### Production Order Lifecycle Transitions
Valid transitions enforced by backend business rules and logged in `state_change_events`:
- `Draft` → `Released`, `Cancelled`
- `Released` → `Planned`, `Scheduled`, `Infeasible`, `Cancelled`
- `Planned` → `Scheduled`, `Infeasible`, `Cancelled`
- `Scheduled` → `In Progress`, `Delayed`, `Infeasible`, `Cancelled`
- `In Progress` → `Completed`, `Delayed`, `Cancelled`
- `Delayed` → `Scheduled`, `In Progress`, `Completed`, `Cancelled`
- `Infeasible` → `Released`, `Planned`, `Scheduled`, `Cancelled`
- `Completed` / `Cancelled` → Terminal states (no further transitions).

