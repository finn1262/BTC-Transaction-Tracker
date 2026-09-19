"""Environment-backed application configuration.

Every source uses a public, keyless API: exchange fetchers read public
market-data endpoints, so no API keys are stored, read, or required.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application settings loaded from environment variables and `.env`.

    Attributes:
        database_path: SQLite database file path.
        log_level: Root logging level.
        http_timeout_seconds: Per-request HTTP timeout.
        max_retries: Maximum attempts per HTTP request.
        default_rate_limit_requests: Default requests per window per endpoint.
        default_rate_limit_window_seconds: Default rate-limit window in seconds.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_path: Path = Path("btc_tracker.db")
    log_level: str = "INFO"
    http_timeout_seconds: float = 30.0
    max_retries: int = 3
    default_rate_limit_requests: int = 10
    default_rate_limit_window_seconds: float = 1.0
