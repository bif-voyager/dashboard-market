from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Market Dashboard API"
    app_env: str = "development"
    api_port: int = 8000
    sqlite_path: str = "data/dashboard.db"
    request_timeout_seconds: int = 20
    sync_on_startup: bool = True
    sync_start_scope: str = "recent"
    sync_periodic_enabled: bool = True
    sync_periodic_interval_seconds: int = 900
    enable_csv_export: bool = True
    app_timezone: str = "UTC"

    dune_api_key: str | None = None
    dune_base_url: str = "https://api.dune.com/api/v1"
    dune_polymarket_query_id: int = 7350670
    dune_kalshi_query_id: int = 7345291
    dune_page_limit: int = 1000
    dune_max_pages: int = 1000
    dune_sql_performance_tier: str = "free"
    dune_sql_poll_interval_seconds: float = 2.0
    dune_sql_max_polls: int = 120
    kalshi_trade_report_fallback_enabled: bool = False
    kalshi_trade_report_fallback_days: str = ""

    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
