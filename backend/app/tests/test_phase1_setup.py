"""
Phase 1 Automated Tests: Verify workspace structure, configuration loading,
and basic FastAPI endpoints.
"""

from pathlib import Path
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, settings
from app.main import app


client = TestClient(app)


def test_required_directories_exist() -> None:
    """Confirm the Phase 1 project directory layout is present."""
    expected_dirs = [
        PROJECT_ROOT / "backend" / "app" / "core",
        PROJECT_ROOT / "backend" / "app" / "database",
        PROJECT_ROOT / "backend" / "app" / "models",
        PROJECT_ROOT / "backend" / "app" / "schemas",
        PROJECT_ROOT / "backend" / "app" / "routers",
        PROJECT_ROOT / "backend" / "app" / "services",
        PROJECT_ROOT / "backend" / "app" / "scheduling",
        PROJECT_ROOT / "backend" / "app" / "generators",
        PROJECT_ROOT / "backend" / "app" / "validators",
        PROJECT_ROOT / "backend" / "app" / "utils",
        PROJECT_ROOT / "backend" / "app" / "tests",
        PROJECT_ROOT / "backend" / "alembic",
        PROJECT_ROOT / "frontend" / "pages",
        PROJECT_ROOT / "frontend" / "css",
        PROJECT_ROOT / "frontend" / "js",
        PROJECT_ROOT / "frontend" / "assets",
        PROJECT_ROOT / "data" / "generated",
        PROJECT_ROOT / "data" / "ground_truth",
        PROJECT_ROOT / "data" / "exports",
        PROJECT_ROOT / "docs",
        PROJECT_ROOT / "scripts",
    ]
    for directory in expected_dirs:
        assert directory.is_dir(), f"Missing directory: {directory}"


def test_required_phase1_documents_exist() -> None:
    """Confirm Phase 1 documentation and config template files exist."""
    expected_files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "DEVELOPMENT_STATUS.md",
        PROJECT_ROOT / "REQUIREMENT_TRACEABILITY.md",
        PROJECT_ROOT / "docs" / "architecture.md",
        PROJECT_ROOT / "backend" / "requirements.txt",
        PROJECT_ROOT / "backend" / ".env.example",
        PROJECT_ROOT / "backend" / ".gitignore",
    ]
    for file_path in expected_files:
        assert Path(file_path).is_file(), f"Missing file: {file_path}"


def test_settings_defaults() -> None:
    """Confirm configuration defaults load properly."""
    assert settings.DB_NAME == "plantops_db"
    assert settings.DEFAULT_RANDOM_SEED == 20261022
    assert "mysql+pymysql://" in settings.database_url
    assert len(settings.cors_origins_list) >= 1


def test_root_endpoint() -> None:
    """Confirm GET / returns application metadata."""
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert "PlantOps" in payload["application"]


def test_health_endpoint() -> None:
    """Confirm GET /health returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database_target"] == "plantops_db"

