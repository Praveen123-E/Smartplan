# PlantOps – Windows Local Setup & Launch Helper Script
# Run from repository root in PowerShell: .\scripts\setup_windows.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== PlantOps Local Windows Setup ===" -ForegroundColor Cyan

Set-Location "$PSScriptRoot\..\backend"

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env from .env.example (edit DB credentials if needed)." -ForegroundColor Yellow
}

Write-Host "Installing Python dependencies from backend\requirements.txt..." -ForegroundColor Green
python -m pip install -r requirements.txt

Write-Host "Running Alembic database migrations (ensure MySQL plantops_db exists)..." -ForegroundColor Green
python -m alembic upgrade head

Write-Host "Generating deterministic full dataset (seed 20261022) and loading into DB..." -ForegroundColor Green
python -m app.generators.generate_data --scale full --seed 20261022 --load-db

Write-Host "Running full Pytest verification suite..." -ForegroundColor Green
python -m pytest -v

Write-Host "`nSetup complete! Launch PlantOps with:" -ForegroundColor Cyan
Write-Host "  cd backend; uvicorn app.main:app --reload --port 8000" -ForegroundColor White
Write-Host "Then open: http://127.0.0.1:8000/ui" -ForegroundColor White

