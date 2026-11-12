# PlantOps – System Architecture Plan

## 1. Purpose & Overview

**PlantOps** is an Intelligent Production Scheduling & Planning System built for manufacturing plants.
It solves the real-world problem of scheduling production orders across factory machines while respecting:

- Product routing & operation sequence
- Machine eligibility & single-operation capacity
- Machine working calendars, shifts, holidays & downtime
- Sequence-dependent changeover (setup) times
- Labor shift availability & capacity
- Material requirements & inventory availability dates
- Shared tooling capacity
- Order priorities & customer due dates

---

## 2. High-Level Architecture (3-Tier Web Application)

```text
+-------------------------------------------------------------------+
|                        1. PRESENTATION TIER                       |
|   Browser (HTML5 + CSS3 + Bootstrap 5 + Vanilla JS + Chart.js)    |
|   - 17 Sidebar Modules   - Interactive Gantt Chart   - Dashboards |
+---------------------------------+---------------------------------+
                                  | HTTP / JSON (REST API + JWT)
                                  v
+-------------------------------------------------------------------+
|                        2. APPLICATION TIER                        |
|                    FastAPI Backend (Python 3.13)                  |
|                                                                   |
|  +------------------+  +------------------+  +-----------------+  |
|  | Routers (REST)   |  | Services Layer   |  | OR-Tools CP-SAT |  |
|  | Auth, Orders,    |->| Business Rules,  |->| Scheduling      |  |
|  | Machines, Gantt  |  | Audit, Validation|  | Engine          |  |
|  +------------------+  +------------------+  +-----------------+  |
|                                                                   |
|  +------------------+  +------------------+                       |
|  | Data Generator   |  | Anomaly & Ground |                       |
|  | (Seed 20261022)  |  | Truth Evaluator  |                       |
|  +------------------+  +------------------+                       |
+---------------------------------+---------------------------------+
                                  | SQLAlchemy ORM + PyMySQL
                                  v
+-------------------------------------------------------------------+
|                          3. DATA TIER                             |
|                     MySQL 8.0 (plantops_db)                       |
|   - Master Data     - Orders & Inventory    - Scheduling Runs     |
|   - Audit Logs      - StateChangeEvents     - ConstraintViolations|
+-------------------------------------------------------------------+
```

### Why This Architecture?
1. **Separation of Concerns**:
   - **Frontend (`frontend/`)**: Handles UI, charts, forms, and Gantt visualization. No business calculations happen here.
   - **Routers (`backend/app/routers/`)**: Validate HTTP requests using Pydantic schemas, check JWT permissions, and call services.
   - **Services (`backend/app/services/`)**: Contain manufacturing rules, status lifecycle checks, and database transactions.
   - **Scheduling (`backend/app/scheduling/`)**: Dedicated module wrapping Google OR-Tools CP-SAT so optimization logic is clean and isolated.
   - **Database (`backend/app/models/`)**: SQLAlchemy ORM models mapped to `plantops_db` in MySQL, versioned with Alembic.

---

## 3. Folder Structure

```text
Smartplan_system/ (plantops root)
|-- backend/
|   |-- app/
|   |   |-- main.py              # FastAPI entry point & router registration
|   |   |-- core/
|   |   |   |-- config.py        # Environment settings (.env loader)
|   |   |   |-- security.py      # Password hashing & JWT token utilities
|   |   |-- database/
|   |   |   |-- connection.py    # SQLAlchemy engine & SessionLocal
|   |   |   |-- base.py          # Declarative base & common timestamp mixin
|   |   |-- models/              # SQLAlchemy ORM tables
|   |   |-- schemas/             # Pydantic request/response DTOs
|   |   |-- routers/             # FastAPI endpoints grouped by domain
|   |   |-- services/            # Business logic & audit trail services
|   |   |-- scheduling/          # OR-Tools CP-SAT solver & objective builder
|   |   |-- generators/          # Deterministic synthetic data generator
|   |   |-- validators/          # Integrity validator & anomaly detector
|   |   |-- utils/               # ID formatters, date helpers, CSV exporters
|   |   |-- tests/               # Pytest automated test suite
|   |-- alembic/                 # Database schema migrations
|   |-- requirements.txt
|   |-- .env.example
|   |-- .gitignore
|-- frontend/
|   |-- index.html               # App shell / login & dashboard entry
|   |-- pages/                   # HTML views for the 17 sidebar modules
|   |-- css/                     # Custom Navy/Indigo enterprise SaaS styles
|   |-- js/                      # API client, charts, Gantt renderer, state
|   |-- assets/                  # Logos & static assets
|-- data/
|   |-- generated/               # Reproducible CSV, JSON, SQL seed exports
|   |-- ground_truth/            # Separate ground_truth.csv & ground_truth.json
|   |-- exports/                 # User-triggered report exports
|-- docs/                        # Architecture, schema, rules, data dictionary
|-- scripts/                     # Helper setup & verification scripts
|-- README.md
|-- DEVELOPMENT_STATUS.md
|-- REQUIREMENT_TRACEABILITY.md
```

---

## 4. Database & Traceability Strategy

- **Database**: MySQL 8.0 (`plantops_db`).
- **Immutable Business IDs**:
  - Product: `PROD-2026-000001`
  - Routing: `ROUTE-{sku}-01`
  - Operation: `OP-{order-id}-01`
  - Machine: `MACH-001`
  - Schedule: `SCH-2026-000001`
  - Material: `MAT-2026-000001`
  - Production Order: `ORD-2026-000001`
- **No Silent Overwrites**:
  - Every scheduling run creates a new `SchedulingRun` record and links `OperationSchedule` rows to that run ID, enabling side-by-side run comparison.
  - Lifecycle transitions (e.g., `Draft -> Released -> Scheduled -> Completed`) are recorded in `StateChangeEvent`.
  - User actions and master data changes are recorded in `AuditLog`.
- **Ground Truth Separation**:
  - `ground_truth.csv` and `ground_truth.json` live in `data/ground_truth/` and are NEVER read by the scheduling engine or anomaly detector. They are used exclusively by the evaluation endpoint (`/api/ground-truth/evaluation`) to compute TP, FP, TN, FN, Precision, Recall, and F1 Score.

---

## 5. Security & Role-Based Access Control (RBAC)

- **Authentication**: OAuth2 / JWT Bearer tokens signed with `HS256` and passwords hashed with `bcrypt`.
- **Roles**:
  1. `Admin` (OT/IT Administrator): Full access, users/roles, system settings, audit logs.
  2. `Production Planner`: Orders, products, routings, run scheduler, Gantt, run comparison, analytics.
  3. `Plant Operator`: View assigned operations & machine schedules, update operation progress, report issues.
  4. `Maintenance/Quality Engineer`: Machine downtime, maintenance records, review & resolve authorized exceptions.
- **Enforcement**: Checked on every backend FastAPI endpoint using dependency injection (`Depends(require_roles(...))`), never just in the UI.

---

## 6. Phased Implementation Plan

1. **Phase 1**: Workspace inspection, architecture, traceability matrix, and backend skeleton setup.
2. **Phase 2**: Database schema, SQLAlchemy models, and Alembic migrations.
3. **Phase 3**: Data dictionary (`docs/data_dictionary.md`) and deterministic synthetic data generator (seed `20261022`).
4. **Phase 4**: Database validation engine and data integrity checks.
5. **Phase 5**: FastAPI backend CRUD APIs (Products, Routings, Machines, Calendars, Shifts, Materials, Orders, Changeovers).
6. **Phase 6**: Google OR-Tools CP-SAT scheduling engine (all 9 hard constraints + configurable multi-objective optimization + infeasibility diagnostics).
7. **Phase 7**: Anomaly detection engine (all 5 mandatory + extended scenarios) & Ground Truth evaluation.
8. **Phase 8**: Professional enterprise dashboard & core frontend pages (Overview + master data views).
9. **Phase 9**: Interactive Gantt chart & scheduling comparison UI.
10. **Phase 10**: Analytics, reports, CSV export, and audit logs UI.
11. **Phase 11**: Full JWT authentication & RBAC enforcement across backend & frontend.
12. **Phase 12**: End-to-end frontend/backend integration & polish across all 17 modules.
13. **Phase 13**: Full Pytest automated suite (20+ core test areas) & bug fixing.
14. **Phase 14**: Final documentation, interview Q&A guides, reproducibility check, and Windows delivery verification.

