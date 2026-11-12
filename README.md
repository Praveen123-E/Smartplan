# PlantOps – Intelligent Production Scheduling & Planning System

**PlantOps** is an enterprise-style manufacturing production scheduling and planning web application built with **FastAPI**, **MySQL**, **SQLAlchemy**, **Google OR-Tools CP-SAT**, and **Bootstrap 5 + Chart.js**.

---

## Project Structure

- `backend/` – FastAPI REST API, SQLAlchemy models, Alembic migrations, OR-Tools scheduler, synthetic data generator, validation & anomaly engines, Pytest tests.
- `frontend/` – Responsive HTML5/CSS3/JS + Bootstrap 5 dashboard, Chart.js analytics, and interactive Gantt chart.
- `data/` – Reproducible synthetic CSV/JSON/SQL exports and isolated ground truth evaluation files.
- `docs/` – Architecture plan, data dictionary, database schema, business rules, scheduling algorithm, and validation report.
- `scripts/` – Helper scripts for Windows setup and verification.

---

## Windows Setup Instructions

### 1. Open Terminal in Project Root
```powershell
cd c:\CandidateWorkspace\Smartplan_system\backend
```

### 2. Create & Activate Python Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables
```powershell
Copy-Item .env.example .env
# Edit .env and set your MySQL DB_PASSWORD and JWT_SECRET_KEY
```

### 5. Create MySQL Database (in MySQL Workbench or MySQL CLI)
```sql
CREATE DATABASE IF NOT EXISTS plantops_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 6. Run Migrations & Synthetic Data (Added in Phases 2 & 3)
```powershell
alembic upgrade head
python -m app.generators.generate_data --scale full --seed 20261022
```

### 7. Start FastAPI Backend
```powershell
uvicorn app.main:app --reload
```
- Swagger API Docs: http://127.0.0.1:8000/docs
- Health Check: http://127.0.0.1:8000/health

### 8. Run Automated Tests
```powershell
pytest
```

---

## Documentation Index

- [Architecture Plan](docs/architecture.md)
- [Requirement Traceability Matrix](REQUIREMENT_TRACEABILITY.md)
- [Development Status](DEVELOPMENT_STATUS.md)

