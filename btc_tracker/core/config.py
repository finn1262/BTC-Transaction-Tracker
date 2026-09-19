"""Environment-backed application configuration.

Every source uses a public, keyless API: exchange fetchers read public
market-data endpoints, so no API keys are stored, read, or required.
"""

from pathlib import Path

from pydantic import Field
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
        poll_interval_seconds: Seconds between live-feed polls per source.
        backfill_pages: Pages fetched per source on its first feed pass.
        poll_pages: Pages fetched per source on later live-feed passes.
        history_limit: Maximum stored transactions hydrated into the feed.
        max_transactions: Maximum transactions kept in the live in-memory store.
        render_limit: Maximum rows rendered in the trade table.
        ui_flush_interval_seconds: Minimum seconds between UI data flushes.
        search_debounce_seconds: Debounce applied to search input changes.
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
    poll_interval_seconds: float = Field(default=5.0, gt=0)
    backfill_pages: int = Field(default=3, ge=1)
    poll_pages: int = Field(default=1, ge=1)
    history_limit: int = Field(default=50_000, ge=1)
    max_transactions: int = Field(default=50_000, ge=1)
    render_limit: int = Field(default=1_000, ge=1)
    ui_flush_interval_seconds: float = Field(default=0.25, gt=0)
    search_debounce_seconds: float = Field(default=0.15, ge=0)
