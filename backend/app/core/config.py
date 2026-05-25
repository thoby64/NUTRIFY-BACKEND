from functools import lru_cache
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    skip_startup_checks: bool = False

    # Database
    database_url: str = Field(default="")
    sqlalchemy_echo: bool = False

    # Security
    secret_key: str = Field(default="")
    access_token_expire_minutes: int = 60 * 24
    allow_public_registration: bool = False

    # API
    api_title: str = "Nutrition Analytics API"
    api_version: str = "1.0.0"
    api_description: str = "API for nutritionists to plan diets based on food nutrient data"

    # Server
    api_port: int = 8000
    api_host: str = "0.0.0.0"

    # Frontend
    frontend_url: str = "http://localhost:5000"

    # CORS
    cors_origins: List[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
    ])
    cors_credentials: bool = False
    cors_methods: List[str] = Field(default_factory=lambda: ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"])
    cors_headers: List[str] = Field(default_factory=lambda: ["Authorization", "Content-Type"])

    @model_validator(mode="after")
    def validate_required_settings(self):
        if not self.database_url:
            raise ValueError("DATABASE_URL must be configured")
        if not self.secret_key:
            raise ValueError("SECRET_KEY must be configured")
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
