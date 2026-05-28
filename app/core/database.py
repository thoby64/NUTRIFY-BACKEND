import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator
from app.core.config import get_settings

settings = get_settings()


def _normalize_database_url(raw_url: str):
    """Apply deployment-safe defaults to the configured database URL."""
    url = make_url(raw_url)
    if (
        os.getenv("RENDER", "").lower() == "true"
        and url.drivername.startswith("postgresql")
        and "sslmode" not in url.query
    ):
        return url.set(query={**dict(url.query), "sslmode": "require"})
    return url

# Create database engine
engine = create_engine(
    _normalize_database_url(settings.database_url),
    echo=settings.sqlalchemy_echo,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
