SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS daily_volume (
    day_utc TEXT NOT NULL,
    platform TEXT NOT NULL,
    normalized_category TEXT NOT NULL DEFAULT 'all',
    turnover_usd REAL NOT NULL,
    source TEXT NOT NULL,
    source_query_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day_utc, platform, normalized_category)
);

CREATE INDEX IF NOT EXISTS idx_daily_volume_day
ON daily_volume (day_utc);

CREATE INDEX IF NOT EXISTS idx_daily_volume_platform_day
ON daily_volume (platform, day_utc);

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
"""
