"""
Application configuration loader for PlantOps.

Reads settings from environment variables (or a `.env` file inside `backend/`)
so that database passwords and JWT secrets are never hardcoded in source code.

Supports both MySQL (production) and SQLite (local development) via DB_ENGINE.
"""

from pathlib import Path
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict


# Base directory pointing to `backend/`
BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    """Centralized configuration object used across the entire backend."""

    # Application Metadata
    APP_NAME: str = "PlantOps – Intelligent Production Scheduling & Planning System"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database Engine Selection: "mysql" or "sqlite"
    # Set DB_ENGINE=sqlite to run without MySQL installed
    DB_ENGINE: str = "sqlite"

    # MySQL Connection Settings (used when DB_ENGINE=mysql)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "plantops_db"

    # SQLite file path (used when DB_ENGINE=sqlite)
    SQLITE_DB_PATH: str = str(BASE_DIR / "plantops.db")

    # Security / JWT Settings
    JWT_SECRET_KEY: str = "plantops-dev-secret-key-change-in-production-2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # CORS Origins (comma-separated string converted to a list via property)
    CORS_ORIGINS: str = (
        "http://127.0.0.1:5500,http://localhost:5500,"
        "http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:8000"
    )

    # Scheduling Engine Defaults
    DEFAULT_SOLVER_TIME_LIMIT_SECONDS: int = 30
    DEFAULT_RANDOM_SEED: int = 20261022

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """Build the SQLAlchemy connection URL based on the chosen engine."""
        if self.DB_ENGINE == "sqlite":
            # SQLite URL: three slashes = relative, four = absolute path
            return f"sqlite:///{self.SQLITE_DB_PATH}"
        # MySQL URL using PyMySQL driver (quote_plus handles special chars like @ in password)
        encoded_password = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{encoded_password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        """Return allowed CORS origins as a clean Python list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


# Single shared settings instance imported by other modules
settings = Settings()

