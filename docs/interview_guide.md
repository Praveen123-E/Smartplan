# PlantOps – Fresher Developer & Technical Interview Guide

Welcome! This guide explains how every module of **PlantOps** works in simple English so you can confidently walk an interviewer through the architecture, database, optimization engine, and UI.

---

## 1. Big Picture: How PlantOps Works End-to-End

Think of PlantOps as the **brain of a smart factory**:
1. **Master Data** defines *what* we make (`Products`), *the steps* to make it (`Routings` & `Operations`), *who* makes it (`Machines`, `LaborShifts`, `SharedTooling`), *when* machines run (`MachineCalendar`, `MachineDowntime`), and *raw materials* (`Materials`, `InventoryLot`).
2. **Production Orders** represent customer requests (*"Make 50 units of SKU-001 by Friday"*). Each order automatically expands into concrete `ProductionOrderOperations`.
3. **Scheduling Engine (`OR-Tools CP-SAT`)** acts like a mathematical puzzle solver: it places every operation onto an eligible machine at an exact start/end time without overlapping machines, exceeding tooling/labor limits, or running during downtime — while minimizing late deliveries and setup changeovers.
4. **Anomaly Detector & Ground Truth Evaluator** independently checks generated schedules for conflicts (like overlaps, late material arrivals, or missing eligibility) and measures detection accuracy using Precision, Recall, and F1 Score.
5. **Enterprise Web Dashboard** visualizes the live KPIs, Chart.js analytics, interactive Gantt timeline, and role-based workflows.

---

## 2. Module-by-Module Simple Walkthrough

### A. Backend (`backend/app/`)
- **`core/config.py` & `core/security.py`**: Loads `.env` settings using Pydantic and handles JWT token signing (`PyJWT`) + password hashing (`bcrypt`) + RBAC role checks (`require_roles`).
- **`database/` & `models/`**: Connects SQLAlchemy 2.0 to MySQL (`plantops_db`) with 28 tables cleanly split across 7 domain modules (`master_data`, `resources`, `materials`, `orders`, `scheduling`, `governance`, `auth`).
- **`generators/generate_data.py`**: Uses a fixed random seed (`20261022`) so anyone can generate the exact same 100 products, 40 machines, 500 orders, 2,000 operations, and 200 materials, plus isolated negative anomaly scenarios for testing.
- **`validators/data_validator.py`**: Runs 14 data quality checks (primary keys, foreign keys, regex business IDs, positive quantities, date order, sequence continuity, FIFO inventory balance, etc.).
- **`scheduling/preprocessor.py` & `solver.py`**:
  - *Preprocessor* converts calendars, breaks, holidays, and downtimes into forbidden blackout intervals and finds the earliest material availability date.
  - *Solver* uses Google OR-Tools CP-SAT (`NewOptionalIntervalVar`, `AddNoOverlap`, `AddCircuit` for sequence-dependent changeovers, `AddCumulative` for labor & tooling) and persists every run independently (`SchedulingRun`).
- **`validators/anomaly_detector.py` & `ground_truth_evaluator.py`**: Never peeks at ground-truth files while scanning; detects real constraint violations and compares results against `data/ground_truth/ground_truth.json`.
- **`routers/`**: Clean REST API endpoints grouped by domain (`auth`, `users`, `dashboard`, `products`, `machines`, `materials`, `orders`, `scheduling`, `exceptions`, `validation`, `audit`).

### B. Frontend (`frontend/`)
- **Single-Shell Enterprise UI (`index.html` + `css/styles.css`)**: Collapsible Navy/Indigo sidebar with 17 modules, sticky top bar with global search & notifications bell, breadcrumbs, and JWT login modal.
- **`js/api.js`**: Wraps `fetch()` to attach JWT Bearer tokens, show Bootstrap toast errors/successes, and render consistent status badges.
- **`js/charts.js`**: Wraps Chart.js for the 6 overview & utilization charts, cleanly destroying old charts before re-rendering.
- **`js/gantt.js`**: Custom pure-JS Gantt chart component rendering machine rows, priority-colored bars, changeover strips, hatched downtime blocks, shift lines, zoom levels (`hour`/`day`/`week`), tooltips, and task modals.
- **`js/pages.js` & `js/app.js`**: Loads HTML fragments dynamically and binds every form, filter, and table directly to FastAPI endpoints.

---

## 3. Top 5 Interview Questions & Sample Answers

### Q1: Why did you use Google OR-Tools CP-SAT instead of simple First-Come-First-Served (FCFS) sorting?
**Answer:** FCFS ignores sequence-dependent changeovers, shared tooling limits, and global lateness trade-offs. With CP-SAT (Constraint Programming), we declare hard manufacturing constraints mathematically (precedence, blackout downtime windows, `AddCircuit` changeover transitions, `AddCumulative` labor/tooling) and let the solver search for a globally feasible, near-optimal schedule — or prove why an order set is `Infeasible`.

### Q2: How do you handle sequence-dependent changeover times in CP-SAT?
**Answer:** Using `model.AddCircuit(...)` per machine with a dummy depot node `0`. Each operation scheduled on machine `m` forms a single directed tour (`0 -> opA -> opB -> 0`). Whenever edge `(opA -> opB)` is active, a constraint enforces `end[opA] + changeover(m, prodA, prodB) <= start[opB]`, and the edge's changeover minutes are added to the total changeover objective.

### Q3: How did you design traceability so historical decisions aren't lost?
**Answer:** Every scheduling optimization creates a new `SchedulingRun` (`RUN-2026-xxxxxx`) and stores its schedule rows linked to `run_id`, so planners can compare past vs. current runs side-by-side. Similarly, status changes write to `StateChangeEvent` (`previous_state -> new_state`, actor, reason) and mutations write to `AuditLog`.

### Q4: How do you prevent data leakage when evaluating your anomaly detector?
**Answer:** Our `anomaly_detector.py` only inspects live database tables and isolated test scenarios (`anomaly_scenarios.json`). It never reads `ground_truth.json`. Only the separate `ground_truth_evaluator.py` compares detector outputs against `ground_truth.json` to calculate True Positives, False Positives, Precision, Recall, and F1 Score.

### Q5: How does authentication and RBAC work between frontend and backend?
**Answer:** Passwords are salted and hashed with `bcrypt`. On login (`POST /api/auth/login`), FastAPI returns a signed JWT containing `sub` (username) and `roles`. The frontend attaches `Authorization: Bearer <token>` on requests, and FastAPI's `require_roles(...)` dependency verifies the role before allowing sensitive operations like editing orders, running the solver, resolving exceptions, or changing system settings.

