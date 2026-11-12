"""
FastAPI entry point for PlantOps.

Initializes the FastAPI application, configures CORS, and registers
all domain API routers.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import PROJECT_ROOT, settings
from app.routers import (
    audit,
    auth,
    dashboard,
    exceptions,
    machines,
    materials,
    orders,
    products,
    scheduling,
    users,
    validation,
)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Enterprise Intelligent Production Scheduling & Planning System "
            "powered by FastAPI, MySQL, and Google OR-Tools CP-SAT."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register domain routers
    application.include_router(auth.router)
    application.include_router(users.router)
    application.include_router(dashboard.router)
    application.include_router(products.router)
    application.include_router(machines.router)
    application.include_router(materials.router)
    application.include_router(orders.router)
    application.include_router(scheduling.router)
    application.include_router(exceptions.router)
    application.include_router(validation.router)
    application.include_router(audit.router)

    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.is_dir():
        application.mount(
            "/ui",
            StaticFiles(directory=str(frontend_dir), html=True),
            name="plantops-ui",
        )

    @application.get("/", tags=["System"])
    def read_root() -> dict[str, str]:
        """Welcome endpoint confirming the PlantOps API is reachable."""
        return {
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "ui": "/ui",
        }

    @application.get("/health", tags=["System"])
    def health_check() -> dict[str, str]:
        """Health-check endpoint used by monitoring and setup verification."""
        return {
            "status": "healthy",
            "environment": settings.APP_ENV,
            "database_target": settings.DB_NAME,
        }

    return application


app = create_application()
