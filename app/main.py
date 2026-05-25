import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.core.database import engine
from app.routes import admin, auth_extended, foods, manager, meal_planning, planning_v2, user_management

settings = get_settings()
logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure process-wide logging once."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root_logger.setLevel(level)


def _migration_versions() -> list[str]:
    migrations_dir = Path(__file__).resolve().parents[2] / "backend" / "migrations"
    return sorted(
        file.stem.split("_")[0]
        for file in migrations_dir.glob("*.sql")
        if file.stem.split("_")[0].isdigit()
    )


def verify_database_ready() -> None:
    """Check that the expected schema is in place before serving traffic."""
    if settings.skip_startup_checks:
        logger.warning("Startup checks skipped because SKIP_STARTUP_CHECKS=true")
        return

    inspector = inspect(engine)
    required_tables = {
        "users",
        "foods",
        "food_nutrients",
        "planning_clients",
        "planning_plans",
        "planning_plan_days",
        "planning_plan_meals",
        "planning_meal_foods",
    }
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        raise RuntimeError(
            "Database schema is incomplete. Run backend/migrations/run_migrations.py first. "
            f"Missing tables: {', '.join(missing_tables)}"
        )

    if "schema_migrations" not in existing_tables:
        logger.warning(
            "schema_migrations table is missing. The schema is present, but migration history is not being tracked."
        )
        return

    with engine.connect() as connection:
        applied_versions = {
            row[0]
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }

    pending_versions = [version for version in _migration_versions() if version not in applied_versions]
    if pending_versions:
        raise RuntimeError(
            "Pending database migrations detected. Run backend/migrations/run_migrations.py first. "
            f"Pending versions: {', '.join(pending_versions)}"
        )


app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_credentials,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

app.include_router(foods.router)
app.include_router(admin.router)
app.include_router(meal_planning.router)
app.include_router(user_management.router)
app.include_router(manager.router)
app.include_router(auth_extended.router)
app.include_router(planning_v2.router)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "static")), name="static")


@app.on_event("startup")
async def startup_event():
    """Initialize app on startup."""
    configure_logging()
    verify_database_ready()
    logger.info("Nutrition Analytics API started in %s mode", settings.app_env)


@app.get("/")
async def root():
    """Root endpoint - returns API information."""
    return {
        "message": "Nutrition Analytics API",
        "version": settings.api_version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
