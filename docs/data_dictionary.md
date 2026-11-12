# PlantOps – Complete Data Dictionary (Mandatory Core Entities)

This document defines the exact schema, constraints, units, allowed values, and validation rules for all **10 mandatory core entities** in `plantops_db` (plus key supporting notes).

---

## 1. `Product` (Table: `products`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `product_id` | `VARCHAR(32)` | Required | Pattern `PROD-YYYY-NNNNNN` | N/A | Primary Key (Unique) | Must match `^PROD-\d{4}-\d{6}$` | None |
| `sku` | `VARCHAR(40)` | Required | Alphanumeric + hyphen | N/A | Unique | Non-empty uppercase code | None |
| `name` | `VARCHAR(150)` | Required | Non-empty text | N/A | Non-unique | Length 2–150 chars | None |
| `category` | `VARCHAR(80)` | Required | Manufacturing category name | N/A | Non-unique | Non-empty string | None |
| `unit_of_measure` | `VARCHAR(20)` | Required | `pcs`, `units`, `sets`, `kg`, `m` | N/A | Non-unique | Must be valid UOM | `pcs` |
| `standard_batch_size` | `INTEGER` | Required | Positive integer (`> 0`) | units | Non-unique | `standard_batch_size > 0` | `10` |
| `description` | `TEXT` | Optional | Free text | N/A | Non-unique | Max 2000 chars | `NULL` |
| `status` | `VARCHAR(30)` | Required | `Active`, `Inactive`, `Discontinued` | N/A | Non-unique | Must be in `ProductStatus` enum | `Active` |
| `created_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | Valid timestamp | Current UTC |
| `updated_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | `updated_at >= created_at` | Current UTC |

---

## 2. `Routing` (Table: `routings`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `routing_id` | `VARCHAR(64)` | Required | Pattern `ROUTE-{sku}-NN` | N/A | Primary Key (Unique) | Must match `^ROUTE-.+-\d{2}$` | None |
| `product_id` | `VARCHAR(32)` | Required | Existing `products.product_id` | N/A | Non-unique (FK) | Must reference valid Product | None |
| `version` | `VARCHAR(16)` | Required | Two-digit string (`01`, `02`...) | N/A | Non-unique | Non-empty version code | `01` |
| `name` | `VARCHAR(150)` | Required | Non-empty text | N/A | Non-unique | Length 2–150 chars | None |
| `is_active` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | Boolean flag | `true` |
| `effective_from` | `DATE` | Optional | Valid calendar date | Date | Non-unique | Valid date | `NULL` |
| `effective_to` | `DATE` | Optional | Valid calendar date | Date | Non-unique | If present, `effective_to >= effective_from` | `NULL` |
| `status` | `VARCHAR(30)` | Required | `Active`, `Draft`, `Archived` | N/A | Non-unique | Allowed routing status | `Active` |
| `created_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | Valid timestamp | Current UTC |
| `updated_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | `updated_at >= created_at` | Current UTC |

---

## 3. `Operation` (Table: `operations` & Order Instance `production_order_operations`)

> Note: `operations` stores reusable master operation templates (`OP-STD-001`), while `production_order_operations` stores concrete order-specific operations (`OP-{order-id}-01`). Both are documented below.

### 3A. Master Operation (`operations`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `operation_code` | `VARCHAR(32)` | Required | Pattern `OP-STD-NNN` | N/A | Primary Key (Unique) | Non-empty operation code | None |
| `name` | `VARCHAR(120)` | Required | Non-empty text | N/A | Non-unique | Length 2–120 chars | None |
| `operation_type` | `VARCHAR(60)` | Required | `Cutting`, `Machining`, `Drilling`, `Grinding`, `Welding`, `Heat Treatment`, `Coating`, `Assembly`, `Inspection` | N/A | Non-unique | Non-empty process type | None |
| `description` | `TEXT` | Optional | Free text | N/A | Non-unique | Optional notes | `NULL` |
| `default_setup_minutes` | `INTEGER` | Required | Non-negative integer (`>= 0`) | minutes | Non-unique | `>= 0` | `15` |
| `default_run_minutes_per_unit` | `FLOAT` | Required | Positive number (`> 0`) | min/unit | Non-unique | `> 0` | `2.0` |
| `required_labor_count` | `INTEGER` | Required | Positive integer (`>= 1`) | operators | Non-unique | `>= 1` | `1` |
| `tooling_id` | `VARCHAR(32)` | Optional | Existing `shared_tooling.tooling_id` | N/A | Non-unique (FK) | Must exist if non-null | `NULL` |
| `status` | `VARCHAR(30)` | Required | `Active`, `Inactive` | N/A | Non-unique | Valid status | `Active` |
| `created_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | Valid timestamp | Current UTC |
| `updated_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | `updated_at >= created_at` | Current UTC |

### 3B. Order Operation Instance (`production_order_operations`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `operation_id` | `VARCHAR(48)` | Required | Pattern `OP-{order-id}-NN` | N/A | Primary Key (Unique) | Must match `^OP-ORD-\d{4}-\d{6}-\d{2}$` | None |
| `order_id` | `VARCHAR(32)` | Required | Existing `production_orders.order_id` | N/A | Non-unique (FK) | Must reference valid ProductionOrder | None |
| `routing_operation_id` | `INTEGER` | Optional | Existing `routing_operations.id` | N/A | Non-unique (FK) | Must exist if non-null | `NULL` |
| `operation_code` | `VARCHAR(32)` | Required | Existing `operations.operation_code` | N/A | Non-unique (FK) | Must reference valid Operation | None |
| `sequence_number` | `INTEGER` | Required | Positive integer (`1, 2, 3...`) | step | Unique per `order_id` | Strictly increasing `1..N` per order | None |
| `planned_duration_minutes` | `INTEGER` | Required | Positive integer (`> 0`) | minutes | Non-unique | `> 0` | None |
| `setup_minutes` | `INTEGER` | Required | Non-negative integer (`>= 0`) | minutes | Non-unique | `>= 0` | `10` |
| `labor_required` | `INTEGER` | Required | Positive integer (`>= 1`) | operators | Non-unique | `>= 1` | `1` |
| `tooling_id` | `VARCHAR(32)` | Optional | Existing `shared_tooling.tooling_id` | N/A | Non-unique (FK) | Must exist if non-null | `NULL` |
| `completed_quantity` | `INTEGER` | Required | Non-negative integer (`>= 0`) | units | Non-unique | `0 <= completed_quantity <= order.quantity` | `0` |
| `actual_start_time` | `DATETIME` | Optional | ISO datetime | UTC | Non-unique | Valid datetime | `NULL` |
| `actual_end_time` | `DATETIME` | Optional | ISO datetime | UTC | Non-unique | If set, `actual_end_time >= actual_start_time` | `NULL` |
| `status` | `VARCHAR(30)` | Required | `Pending`, `Scheduled`, `In Progress`, `Completed`, `Delayed`, `Cancelled` | N/A | Non-unique | In `OperationExecutionStatus` enum | `Pending` |

---

## 4. `Machine` (Table: `machines`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `machine_id` | `VARCHAR(32)` | Required | Pattern `MACH-NNN` | N/A | Primary Key (Unique) | Must match `^MACH-\d{3}$` | None |
| `name` | `VARCHAR(120)` | Required | Non-empty text | N/A | Non-unique | Length 2–120 chars | None |
| `machine_type` | `VARCHAR(60)` | Required | `CNC Lathe`, `CNC Mill`, `Laser Cutter`, `Press`, `Welding Cell`, `Grinder`, `Heat Furnace`, `Paint Booth`, `Assembly Station`, `CMM Tester` | N/A | Non-unique | Non-empty machine type | None |
| `work_center` | `VARCHAR(60)` | Required | Work center code (`WC-*`) | N/A | Non-unique | Non-empty code | None |
| `capacity_per_hour` | `FLOAT` | Required | Positive float (`> 0`) | units/hr | Non-unique | `> 0` | `10.0` |
| `concurrent_job_capacity` | `INTEGER` | Required | Positive integer (`>= 1`) | jobs | Non-unique | `>= 1` (typically `1`) | `1` |
| `capabilities` | `TEXT` | Optional | Comma-separated or JSON capabilities | N/A | Non-unique | Optional text | `NULL` |
| `hourly_operating_cost` | `FLOAT` | Required | Non-negative float (`>= 0`) | USD/hr | Non-unique | `>= 0` | `50.0` |
| `status` | `VARCHAR(30)` | Required | `Available`, `Running`, `Maintenance`, `Down`, `Inactive` | N/A | Non-unique | Must be in `MachineStatus` enum | `Available` |
| `created_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | Valid timestamp | Current UTC |
| `updated_at` | `DATETIME` | Required | ISO UTC datetime | UTC | Non-unique | `updated_at >= created_at` | Current UTC |

---

## 5. `MachineCalendar` (Table: `machine_calendars`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `calendar_id` | `INTEGER` | Required | Positive integer | N/A | Primary Key (Auto) | Auto-increment PK | Auto |
| `machine_id` | `VARCHAR(32)` | Required | Existing `machines.machine_id` | N/A | Unique with `(calendar_date, shift_name)` | Must reference valid Machine | None |
| `calendar_date` | `DATE` | Required | Valid calendar date | Date | Part of composite UK | Valid date | None |
| `day_of_week` | `VARCHAR(15)` | Required | `Monday`..`Sunday` | N/A | Non-unique | Must match `calendar_date` weekday | None |
| `is_working_day` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | Boolean | `true` |
| `is_holiday` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | If `true`, `is_working_day` should be `false` | `false` |
| `shift_name` | `VARCHAR(40)` | Required | `Day Shift`, `Evening Shift`, `Night Shift` | N/A | Part of composite UK | Non-empty shift name | `Day Shift` |
| `shift_start_time` | `TIME` | Required | `00:00:00`–`23:59:59` | HH:MM:SS | Non-unique | Valid time | None |
| `shift_end_time` | `TIME` | Required | `00:00:00`–`23:59:59` | HH:MM:SS | Non-unique | `shift_end_time > shift_start_time` for same-day shifts | None |
| `break_start_time` | `TIME` | Optional | Time within shift window | HH:MM:SS | Non-unique | Within `[shift_start_time, shift_end_time]` | `NULL` |
| `break_end_time` | `TIME` | Optional | Time within shift window | HH:MM:SS | Non-unique | `break_end_time > break_start_time` | `NULL` |
| `available_minutes` | `INTEGER` | Required | Non-negative integer (`0..1440`) | minutes | Non-unique | `0` if non-working/holiday else `(shift - break)` | `450` |
| `notes` | `VARCHAR(255)` | Optional | Free text | N/A | Non-unique | Optional comment | `NULL` |

---

## 6. `Material` (Table: `materials`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `material_id` | `VARCHAR(32)` | Required | Pattern `MAT-YYYY-NNNNNN` | N/A | Primary Key (Unique) | Must match `^MAT-\d{4}-\d{6}$` | None |
| `name` | `VARCHAR(150)` | Required | Non-empty text | N/A | Non-unique | Length 2–150 chars | None |
| `category` | `VARCHAR(80)` | Required | `Raw Metal`, `Fastener`, `Electronic`, `Polymer`, `Coating`, `Packaging` | N/A | Non-unique | Non-empty category | None |
| `unit` | `VARCHAR(20)` | Required | `kg`, `pcs`, `liters`, `meters`, `sheets` | N/A | Non-unique | Valid unit | `kg` |
| `unit_cost` | `FLOAT` | Required | Non-negative float (`>= 0`) | USD | Non-unique | `>= 0` | `10.0` |
| `reorder_level` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `>= 0` | `50.0` |
| `available_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `>= 0` in normal operations | `0.0` |
| `reserved_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `>= 0` | `0.0` |
| `consumed_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `>= 0` | `0.0` |
| `stock_status` | `VARCHAR(30)` | Required | `In Stock`, `Low Stock`, `Out of Stock`, `Delayed` | N/A | Non-unique | Must be in `StockStatus` enum | `In Stock` |
| `status` | `VARCHAR(30)` | Required | `Active`, `Inactive` | N/A | Non-unique | Valid status | `Active` |

---

## 7. `InventoryLot` (Table: `inventory_lots`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `lot_id` | `INTEGER` | Required | Positive integer | N/A | Primary Key (Auto) | Auto-increment PK | Auto |
| `material_id` | `VARCHAR(32)` | Required | Existing `materials.material_id` | N/A | Non-unique (FK) | Must reference valid Material | None |
| `lot_number` | `VARCHAR(64)` | Required | Pattern `LOT-YYYY-NNNNNN` | N/A | Unique | Unique lot code | None |
| `initial_quantity` | `FLOAT` | Required | Positive float (`> 0`) | material unit | Non-unique | `> 0` | None |
| `available_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `0 <= available <= initial` | None |
| `reserved_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `>= 0` | `0.0` |
| `consumed_quantity` | `FLOAT` | Required | Non-negative float (`>= 0`) | material unit | Non-unique | `available + reserved + consumed <= initial` | `0.0` |
| `availability_date` | `DATE` | Required | Valid calendar date | Date | Non-unique | Date lot becomes usable | None |
| `expiry_date` | `DATE` | Optional | Valid calendar date | Date | Non-unique | If set, `expiry_date > availability_date` | `NULL` |
| `supplier_name` | `VARCHAR(120)` | Optional | Supplier company name | N/A | Non-unique | Optional text | `NULL` |
| `is_delayed` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | Flags delayed supplier delivery | `false` |
| `status` | `VARCHAR(30)` | Required | `Available`, `Reserved`, `Depleted`, `Delayed`, `Quarantined` | N/A | Non-unique | Valid lot status | `Available` |

---

## 8. `ProductionOrder` (Table: `production_orders`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `order_id` | `VARCHAR(32)` | Required | Pattern `ORD-YYYY-NNNNNN` | N/A | Primary Key (Unique) | Must match `^ORD-\d{4}-\d{6}$` | None |
| `product_id` | `VARCHAR(32)` | Required | Existing `products.product_id` | N/A | Non-unique (FK) | Must reference valid Product | None |
| `routing_id` | `VARCHAR(64)` | Required | Existing `routings.routing_id` | N/A | Non-unique (FK) | Routing must belong to `product_id` | None |
| `quantity` | `INTEGER` | Required | Positive integer (`> 0`) | units | Non-unique | `quantity > 0` | None |
| `completed_quantity` | `INTEGER` | Required | Non-negative integer | units | Non-unique | `0 <= completed_quantity <= quantity` | `0` |
| `priority` | `INTEGER` | Required | `1` (Urgent), `2` (High), `3` (Normal), `4` (Low), `5` (Backlog) | rank | Non-unique | `1 <= priority <= 5` | `3` |
| `customer_name` | `VARCHAR(120)` | Optional | Customer name | N/A | Non-unique | Optional text | `NULL` |
| `release_date` | `DATETIME` | Required | ISO datetime | UTC | Non-unique | Valid datetime | None |
| `due_date` | `DATETIME` | Required | ISO datetime | UTC | Non-unique | `due_date > release_date` | None |
| `is_urgent` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | `true` when `priority == 1` | `false` |
| `status` | `VARCHAR(30)` | Required | `Draft`, `Released`, `Planned`, `Scheduled`, `In Progress`, `Completed`, `Delayed`, `Cancelled`, `Infeasible` | N/A | Non-unique | Must follow valid lifecycle transitions | `Draft` |
| `notes` | `TEXT` | Optional | Free text | N/A | Non-unique | Optional text | `NULL` |

---

## 9. `OperationSchedule` (Table: `operation_schedules`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `schedule_id` | `VARCHAR(32)` | Required | Pattern `SCH-YYYY-NNNNNN` | N/A | Primary Key (Unique) | Must match `^SCH-\d{4}-\d{6}$` | None |
| `run_id` | `VARCHAR(32)` | Required | Existing `scheduling_runs.run_id` | N/A | Non-unique (FK) | Must reference valid SchedulingRun | None |
| `order_id` | `VARCHAR(32)` | Required | Existing `production_orders.order_id` | N/A | Non-unique (FK) | Must reference valid ProductionOrder | None |
| `order_operation_id` | `VARCHAR(48)` | Required | Existing `production_order_operations.operation_id` | N/A | Unique per `run_id` | Must belong to `order_id` | None |
| `machine_id` | `VARCHAR(32)` | Required | Existing `machines.machine_id` | N/A | Non-unique (FK) | Must be eligible for the operation | None |
| `labor_shift_id` | `INTEGER` | Optional | Existing `labor_shifts.shift_id` | N/A | Non-unique (FK) | Must exist if non-null | `NULL` |
| `start_time` | `DATETIME` | Required | ISO datetime | UTC | Non-unique | Must fit inside working calendar & outside downtime | None |
| `end_time` | `DATETIME` | Required | ISO datetime | UTC | Non-unique | `end_time > start_time` | None |
| `duration_minutes` | `INTEGER` | Required | Positive integer (`> 0`) | minutes | Non-unique | Matches `(end_time - start_time)` in minutes | None |
| `changeover_minutes` | `INTEGER` | Required | Non-negative integer (`>= 0`) | minutes | Non-unique | Must match `ChangeoverMatrix` transition | `0` |
| `changeover_start_time` | `DATETIME` | Optional | ISO datetime | UTC | Non-unique | If `changeover_minutes > 0`, `<= start_time` | `NULL` |
| `is_late` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | `end_time > order.due_date` | `false` |
| `lateness_minutes` | `INTEGER` | Required | Non-negative integer (`>= 0`) | minutes | Non-unique | `max(0, end_time - order.due_date)` | `0` |
| `status` | `VARCHAR(30)` | Required | `Scheduled`, `In Progress`, `Completed`, `Cancelled` | N/A | Non-unique | Valid status | `Scheduled` |

---

## 10. `ChangeoverMatrix` (Table: `changeover_matrix`)

| Field Name | Data Type | Req / Opt | Allowed Values | Units | Uniqueness | Validation Rule | Default Value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | Required | Positive integer | N/A | Primary Key (Auto) | Auto-increment PK | Auto |
| `machine_id` | `VARCHAR(32)` | Optional | Existing `machines.machine_id` or `NULL` (plant default) | N/A | Part of composite UK | Must exist if non-null | `NULL` |
| `from_product_id` | `VARCHAR(32)` | Required | Existing `products.product_id` | N/A | Part of composite UK | Must reference valid Product | None |
| `to_product_id` | `VARCHAR(32)` | Required | Existing `products.product_id` | N/A | Part of composite UK | Must reference valid Product | None |
| `changeover_minutes` | `INTEGER` | Required | Non-negative integer (`>= 0`) | minutes | Non-unique | `0` when `from_product_id == to_product_id`, else `> 0` | None |
| `cleaning_required` | `BOOLEAN` | Required | `true`, `false` | N/A | Non-unique | Boolean | `false` |
| `notes` | `VARCHAR(255)` | Optional | Free text | N/A | Non-unique | Optional transition description | `NULL` |

