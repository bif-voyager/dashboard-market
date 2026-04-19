from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Market Dashboard API"
    app_env: str = "development"
    api_port: int = 8000
    sqlite_path: str = "data/dashboard.db"
    request_timeout_seconds: int = 20
    fetch_concurrency: int = 2
    sync_on_startup: bool = True
    sync_start_scope: str = "recent"
    enable_csv_export: bool = True
    app_timezone: str = "UTC"

    poly_gamma_base_url: str = "https://gamma-api.polymarket.com"
    poly_data_base_url: str = "https://data-api.polymarket.com"
    poly_page_limit: int = 500
    poly_recent_max_pages: int = 3
    poly_bootstrap_max_pages: int = 3
    poly_metadata_recent_max_pages: int = 20
    poly_metadata_bootstrap_max_pages: int = 120

    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_page_limit: int = 1000
    kalshi_recent_max_pages: int = 16
    kalshi_bootstrap_max_pages: int = 120
    kalshi_event_recent_max_pages: int = 18
    kalshi_event_bootstrap_max_pages: int = 180
    kalshi_historical_market_recent_max_pages: int = 18
    kalshi_historical_market_bootstrap_max_pages: int = 180
    kalshi_candlestick_chunk_size: int = 100
    kalshi_recent_trade_window_days: int = 1
    kalshi_trade_window_max_pages: int = 20
    kalshi_trade_min_window_hours: int = 1

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
