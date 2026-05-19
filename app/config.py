import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic.dataclasses import dataclass

load_dotenv()


def _csv_env(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Centralized runtime settings loaded from environment variables."""

    app_name: str = os.getenv("APP_NAME", "PrepVicta Backend")
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    environment: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    allowed_origins: list[str] = Field(
        default_factory=lambda: _csv_env(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174,"
            "http://localhost:3000,http://127.0.0.1:3000",
        )
    )
    enforce_origin: bool = os.getenv("ENFORCE_ORIGIN", "false").lower() == "true"
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    cache_max_items: int = int(os.getenv("CACHE_MAX_ITEMS", "512"))

    db_host: str = os.getenv("SUPABASE_HOST", "")
    db_port: int = int(os.getenv("SUPABASE_PORT", "5432"))
    db_name: str = os.getenv("SUPABASE_DB", "")
    db_user: str = os.getenv("SUPABASE_USER", "")
    db_password: str = os.getenv("SUPABASE_PASSWORD", "")
    db_schema: str = os.getenv("SUPABASE_SCHEMA", "public")
    db_min_pool_size: int = int(os.getenv("DB_MIN_POOL_SIZE", "1"))
    db_max_pool_size: int = int(os.getenv("DB_MAX_POOL_SIZE", "10"))
    db_command_timeout_seconds: int = int(os.getenv("DB_COMMAND_TIMEOUT_SECONDS", "30"))

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_PLANNING_MODEL", "gpt-4o-mini")
    openai_timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))
    openai_max_concurrency: int = int(os.getenv("OPENAI_MAX_CONCURRENCY", "8"))

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")

    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", os.getenv("pinecone_api_key", ""))
    pinecone_index: str = os.getenv("PINECONE_INDEX", "")
    pinecone_namespace: str = os.getenv("PINECONE_NAMESPACE", "")

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.lower().strip()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_required_for_startup(self) -> None:
        missing = [
            name
            for name, value in {
                "SUPABASE_HOST": self.db_host,
                "SUPABASE_DB": self.db_name,
                "SUPABASE_USER": self.db_user,
                "SUPABASE_PASSWORD": self.db_password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
