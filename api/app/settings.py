from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://ivay:ivay_dev@localhost:5432/ivay"
    # Public ingest hardening (spec 9.3).
    max_body_bytes: int = 64 * 1024
    # Order webhooks are bigger than event batches, and are authenticated by HMAC.
    webhook_max_body_bytes: int = 1024 * 1024
    rate_limit_per_minute: int = 600
    # A built config above this size is refused and recorded in NOTES.md (spec 7.1).
    config_max_bytes: int = 50 * 1024
    config_cache_seconds: int = 60
