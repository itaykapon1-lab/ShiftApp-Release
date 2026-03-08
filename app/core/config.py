"""Application Configuration Settings.

This module contains all application-wide settings using Pydantic's BaseSettings
for environment variable support and type validation.

HYBRID DATABASE MODE:
- Default: SQLite (no env vars needed) -> Easy local development
- Production: PostgreSQL (set DATABASE_URL env var) -> Scalable production
"""

import os
from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # ========================================
    # Database Configuration (Hybrid Mode)
    # ========================================
    # If DATABASE_URL is set in environment, use it (PostgreSQL for production)
    # Otherwise, default to SQLite for simple local development
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///scheduler.db"
    )

    # PostgreSQL connection pool settings (ignored for SQLite)
    db_pool_size: int = 10          # 20 users ÷ 2 = 10 connections
    db_max_overflow: int = 5        # Burst capacity
    db_pool_pre_ping: bool = True   # Auto-reconnect stale connections

    # ========================================
    # Session & Security Configuration
    # ========================================
    # CRITICAL: Use environment variable in production!
    secret_key: str = os.environ.get(
        "SECRET_KEY",
        "dev-secret-key-change-in-production"
    )
    session_cookie_name: str = "session_id"
    session_max_age: int = 86400 * 7  # 7 days in seconds

    # Environment detection for security settings
    environment: str = os.environ.get("ENVIRONMENT", "development")

    # ========================================
    # API Configuration
    # ========================================
    api_title: str = "Shift Scheduling API"
    api_version: str = "1.0.0"
    api_description: str = "FastAPI backend for shift scheduling optimization"

    # ========================================
    # CORS Configuration
    # ========================================
    # Can be overridden via CORS_ORIGINS env var (comma-separated)
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ]

    # ========================================
    # File Upload Configuration
    # ========================================
    max_file_size_mb: int = 10  # Maximum upload size in MB

    # ========================================
    # Solver Configuration
    # ========================================
    solver_max_workers: int = 4  # ProcessPoolExecutor worker count

    @property
    def max_file_size_bytes(self) -> int:
        """Returns max file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        """Returns True if using SQLite database."""
        return "sqlite" in self.database_url.lower()

    @property
    def is_postgres(self) -> bool:
        """Returns True if using PostgreSQL database."""
        return "postgresql" in self.database_url.lower() or "postgres" in self.database_url.lower()

    @property
    def is_production(self) -> bool:
        """Returns True if running in production environment."""
        return self.environment.lower() == "production"

    @property
    def cookie_secure(self) -> bool:
        """Returns True if cookies should use Secure flag (HTTPS only)."""
        return self.is_production

    class Config:
        env_file = ".env"
        case_sensitive = False
        # Support comma-separated CORS_ORIGINS in env
        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str):
            if field_name == "cors_origins":
                return [origin.strip() for origin in raw_val.split(",")]
            return raw_val


# Global settings instance
settings = Settings()
