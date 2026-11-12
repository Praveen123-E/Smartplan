"""
Database engine, session factory, and FastAPI dependency for PlantOps.

Supports both MySQL (production) and SQLite (local development).
The engine type is chosen automatically based on `settings.DB_ENGINE`.
"""

from collections.abc import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


# Build engine kwargs depending on the database backend
_engine_kwargs: dict = {"echo": False}

if settings.DB_ENGINE == "sqlite":
    # SQLite requires `check_same_thread=False` for FastAPI's thread pool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # MySQL-specific pool settings
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 3600


# Create the SQLAlchemy engine (SQLite or MySQL based on config)
engine = create_engine(settings.database_url, **_engine_kwargs)


# Enable WAL mode and foreign keys for SQLite (better concurrency & integrity)
if settings.DB_ENGINE == "sqlite":
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# Session factory used by API requests and background scripts
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it safely."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """Run a lightweight `SELECT 1` query to verify database connectivity."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        return result.scalar() == 1

