# PlantOps – Synthetic Dataset Documentation

## Overview

This directory contains the **complete deterministic synthetic manufacturing dataset** for PlantOps. All data is 100% synthetic — no external or proprietary data sources are used.

---

## Generator Command

```bash
cd backend
python -m app.generators.generate_data --scale full --seed 20261022
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--scale` | `starter` (10 products, 30 orders) or `full` (100 products, 500 orders) | `full` |
| `--seed` | Fixed random seed for deterministic reproducibility | `20261022` |
| `--load-db` | Also insert generated data into the configured MySQL/SQLite database | Off |

---

## Fixed Seed

**Seed: `20261022`**

All random operations (`random`, `numpy`, `pandas`) are seeded with this value at the start of every generation run. This guarantees that running the generator twice with the same seed and scale produces **byte-identical** output files.

---

## Dataset Scale

| Entity | Starter | Full |
|--------|---------|------|
| Products / SKUs | 10 | 100 |
| Machines | 8 | 40 |
| Production Orders | 30 | 500 |
| Operations | 120 | 2,000 |
| Materials | 25 | 200 |
| Routings | 10 | 100 |
| Machine Calendars | 112 | 560 |
| Changeover Matrix | ~1,000 | ~10,000 |
| Inventory Lots | 50 | 400 |
| Labor Shifts | 12 | 12 |

---

## Directory Structure

```
data/
├── README.md                          ← This file
├── exports/                           ← Reserved for user CSV/report exports
├── generated/
│   ├── csv/                           ← CSV exports of all tables
│   │   ├── products.csv
│   │   ├── routings.csv
│   │   ├── machines.csv
│   │   ├── production_orders.csv
│   │   ├── operation_schedules.csv
│   │   ├── changeover_matrix.csv
│   │   ├── ... (27 CSV files total)
│   │   └── anomaly_scenarios.csv
│   ├── json/                          ← JSON exports of all tables
│   │   ├── products.json
│   │   ├── routings.json
│   │   ├── ... (27 JSON files total)
│   ├── plantops_seed.sql              ← SQL INSERT statements for MySQL import
│   ├── anomaly_scenarios.json         ← Injected edge-case scenarios (labelled)
│   └── source_manifest.json           ← Row counts + SHA-256 checksums
└── ground_truth/
    ├── ground_truth.csv               ← Expected anomaly labels (separate from inputs)
    └── ground_truth.json              ← Same data in JSON format
```

---

## Schema / Core Entities (10 Mandatory)

| # | Entity | Table Name | Primary Key | Description |
|---|--------|-----------|-------------|-------------|
| 1 | Product | `products` | `product_id` (`PROD-2026-NNNNNN`) | Manufactured SKUs |
| 2 | Routing | `routings` | `routing_id` (`ROUTE-<SKU>-01`) | Manufacturing process routes |
| 3 | Operation | `operations` | `operation_id` | Generic operation templates |
| 4 | Machine | `machines` | `machine_id` (`MACH-NNN`) | Shop-floor machines |
| 5 | MachineCalendar | `machine_calendars` | `id` (auto) | Daily shift schedules per machine |
| 6 | Material | `materials` | `material_id` (`MAT-2026-NNNNNN`) | Raw materials / components |
| 7 | InventoryLot | `inventory_lots` | `id` (auto) | Stock lots with availability dates |
| 8 | ProductionOrder | `production_orders` | `order_id` (`ORD-2026-NNNNNN`) | Manufacturing orders with due dates |
| 9 | OperationSchedule | `operation_schedules` | `schedule_id` (`SCH-2026-NNNNNN`) | Scheduled time slots on machines |
| 10 | ChangeoverMatrix | `changeover_matrix` | `id` (auto) | Sequence-dependent setup times |

Full field-level documentation: [`docs/data_dictionary.md`](../docs/data_dictionary.md)

---

## Generation Order (Parent → Child)

The generator creates records in this strict dependency order to ensure all foreign keys are valid:

1. Products
2. Routings
3. Shared Tooling
4. Operations (templates)
5. Routing Operations (links routings → operations)
6. Machines
7. Operation Machine Eligibility (links operations → machines)
8. Machine Calendars
9. Machine Downtime
10. Labor Shifts
11. Labor Resources
12. Materials
13. Inventory Lots
14. Material Requirements
15. Production Orders
16. Production Order Operations
17. Changeover Matrix
18. Scheduling Runs + Operation Schedules + Tooling Allocations
19. Roles, Users, User Roles
20. State Change Events, Audit Logs, Notifications

---

## Edge Cases / Anomaly Scenarios

The generator injects **5 mandatory labelled negative scenarios** after creating valid baseline data:

| # | Scenario | Issue Type | Description |
|---|----------|-----------|-------------|
| 1 | Machine Overlap | `MachineOverlap` | Two operations scheduled concurrently on a single-capacity machine |
| 2 | Precedence Violation | `PrecedenceViolation` | Operation step 2 starts before step 1 finishes |
| 3 | Material Before Availability | `MaterialBeforeAvailability` | Material consumed before inventory lot availability date |
| 4 | Outside Shift Calendar | `OutsideShiftCalendar` | Operation scheduled outside machine's working hours |
| 5 | Changeover Omitted | `ChangeoverOmitted` | Product changeover time not accounted for between different products |

Plus **3 extended scenarios**: downtime overlap, tooling overallocation, labor capacity exceeded.

These are stored in `generated/anomaly_scenarios.json` with explicit `issue_type` labels. Ground truth labels are in `ground_truth/` and are **never** included in input feature files.

---

## Source Manifest

`generated/source_manifest.json` contains:

- **Row counts** for every generated table
- **SHA-256 checksums** for every exported CSV, JSON, and SQL file
- **Scale** and **seed** used for generation
- **Reference timestamp** for all generated datetime values

---

## Reproducibility Verification

Run the verification script to confirm deterministic output:

```bash
cd backend
python ../scripts/verify_reproducibility.py --seed 20261022 --scale full
```

This regenerates the dataset **twice** with the same seed and compares:
- Row counts per table
- SHA-256 checksums of every file

Expected output: `✅ REPRODUCIBILITY VERIFIED`

---

## Lawful Use & Provenance

- **Source**: 100% synthetic data generated by `backend/app/generators/generate_data.py`
- **External data**: None used
- **License**: No third-party data dependencies
- **Personal data**: None — all names, IDs, and values are fabricated
- **Attribution**: Schema inspired by standard manufacturing ERP concepts (MRP-II, APS)

