SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS market_registry (
    platform TEXT NOT NULL,
    market_key TEXT NOT NULL,
    event_key TEXT,
    series_key TEXT,
    title TEXT,
    raw_category TEXT,
    normalized_category TEXT NOT NULL,
    source TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, market_key)
);

CREATE INDEX IF NOT EXISTS idx_market_registry_platform_category
ON market_registry (platform, normalized_category);

CREATE TABLE IF NOT EXISTS seen_trade (
    platform TEXT NOT NULL,
    trade_key TEXT NOT NULL,
    market_key TEXT NOT NULL,
    trade_ts TEXT NOT NULL,
    day_utc TEXT NOT NULL,
    normalized_category TEXT NOT NULL,
    turnover_usd REAL NOT NULL,
    source TEXT,
    PRIMARY KEY (platform, trade_key)
);

CREATE INDEX IF NOT EXISTS idx_seen_trade_platform_day
ON seen_trade (platform, day_utc);

CREATE TABLE IF NOT EXISTS daily_volume (
    day_utc TEXT NOT NULL,
    platform TEXT NOT NULL,
    normalized_category TEXT NOT NULL,
    turnover_usd REAL NOT NULL,
    trades_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day_utc, platform, normalized_category)
);

CREATE INDEX IF NOT EXISTS idx_daily_volume_day
ON daily_volume (day_utc);

CREATE TABLE IF NOT EXISTS sync_state (
    platform TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    last_cursor TEXT,
    partial INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (platform, scope)
);

CREATE TABLE IF NOT EXISTS category_snapshot (
    platform TEXT NOT NULL,
    normalized_category TEXT NOT NULL,
    volume_24h REAL NOT NULL DEFAULT 0,
    volume_1wk REAL NOT NULL DEFAULT 0,
    volume_1mo REAL NOT NULL DEFAULT 0,
    volume_total REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, normalized_category)
);
"""
