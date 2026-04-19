from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from app.db.database import Database


@dataclass(slots=True)
class MarketRecord:
    platform: str
    market_key: str
    title: str | None
    raw_category: str | None
    normalized_category: str
    event_key: str | None = None
    series_key: str | None = None
    source: str | None = None


@dataclass(slots=True)
class TradeRecord:
    platform: str
    trade_key: str
    market_key: str
    trade_ts: str
    day_utc: str
    normalized_category: str
    turnover_usd: float
    source: str | None = None


@dataclass(slots=True)
class CategorySnapshotRecord:
    platform: str
    normalized_category: str
    volume_24h: float
    volume_1wk: float
    volume_1mo: float
    volume_total: float


@dataclass(slots=True)
class DailyVolumeRecord:
    platform: str
    day_utc: str
    normalized_category: str
    turnover_usd: float
    trades_count: int = 0


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_markets(self, records: Iterable[MarketRecord]) -> int:
        prepared = list(records)
        if not prepared:
            return 0
        now = datetime.now(UTC).isoformat()
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO market_registry (
                    platform,
                    market_key,
                    event_key,
                    series_key,
                    title,
                    raw_category,
                    normalized_category,
                    source,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, market_key) DO UPDATE SET
                    event_key = excluded.event_key,
                    series_key = excluded.series_key,
                    title = excluded.title,
                    raw_category = excluded.raw_category,
                    normalized_category = excluded.normalized_category,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        record.platform,
                        record.market_key,
                        record.event_key,
                        record.series_key,
                        record.title,
                        record.raw_category,
                        record.normalized_category,
                        record.source,
                        now,
                    )
                    for record in prepared
                ],
            )
        return len(prepared)

    def get_market_category(self, platform: str, market_key: str) -> str | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT normalized_category
                FROM market_registry
                WHERE platform = ? AND market_key = ?
                """,
                (platform, market_key),
            ).fetchone()
        return None if row is None else row["normalized_category"]

    def record_trades(self, records: Iterable[TradeRecord]) -> int:
        prepared = list(records)
        if not prepared:
            return 0
        platform = prepared[0].platform
        trade_keys = [record.trade_key for record in prepared]
        inserted_records: list[TradeRecord] = []

        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing: set[str] = set()
            chunk_size = 250
            for index in range(0, len(trade_keys), chunk_size):
                chunk = trade_keys[index : index + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT trade_key
                    FROM seen_trade
                    WHERE platform = ? AND trade_key IN ({placeholders})
                    """,
                    [platform, *chunk],
                ).fetchall()
                existing.update(row["trade_key"] for row in rows)

            for record in prepared:
                if record.trade_key not in existing:
                    inserted_records.append(record)

            if not inserted_records:
                return 0

            connection.executemany(
                """
                INSERT INTO seen_trade (
                    platform,
                    trade_key,
                    market_key,
                    trade_ts,
                    day_utc,
                    normalized_category,
                    turnover_usd,
                    source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.platform,
                        record.trade_key,
                        record.market_key,
                        record.trade_ts,
                        record.day_utc,
                        record.normalized_category,
                        record.turnover_usd,
                        record.source,
                    )
                    for record in inserted_records
                ],
            )

            now = datetime.now(UTC).isoformat()
            aggregated: dict[tuple[str, str, str], dict[str, float | int]] = defaultdict(
                lambda: {"turnover_usd": 0.0, "trades_count": 0}
            )
            for record in inserted_records:
                bucket = (record.day_utc, record.platform, record.normalized_category)
                aggregated[bucket]["turnover_usd"] += record.turnover_usd
                aggregated[bucket]["trades_count"] += 1

            connection.executemany(
                """
                INSERT INTO daily_volume (
                    day_utc,
                    platform,
                    normalized_category,
                    turnover_usd,
                    trades_count,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_utc, platform, normalized_category) DO UPDATE SET
                    turnover_usd = daily_volume.turnover_usd + excluded.turnover_usd,
                    trades_count = daily_volume.trades_count + excluded.trades_count,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        day_utc,
                        bucket_platform,
                        category,
                        values["turnover_usd"],
                        values["trades_count"],
                        now,
                    )
                    for (day_utc, bucket_platform, category), values in aggregated.items()
                ],
            )
        return len(inserted_records)

    def upsert_category_snapshots(self, records: Iterable[CategorySnapshotRecord]) -> int:
        prepared = list(records)
        if not prepared:
            return 0
        now = datetime.now(UTC).isoformat()
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO category_snapshot (
                    platform,
                    normalized_category,
                    volume_24h,
                    volume_1wk,
                    volume_1mo,
                    volume_total,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, normalized_category) DO UPDATE SET
                    volume_24h = excluded.volume_24h,
                    volume_1wk = excluded.volume_1wk,
                    volume_1mo = excluded.volume_1mo,
                    volume_total = excluded.volume_total,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        record.platform,
                        record.normalized_category,
                        record.volume_24h,
                        record.volume_1wk,
                        record.volume_1mo,
                        record.volume_total,
                        now,
                    )
                    for record in prepared
                ],
            )
        return len(prepared)

    def replace_daily_volumes(
        self,
        *,
        platform: str,
        start_day: str,
        end_day: str,
        records: Iterable[DailyVolumeRecord],
    ) -> int:
        prepared = list(records)
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM daily_volume
                WHERE platform = ? AND day_utc >= ? AND day_utc <= ?
                """,
                (platform, start_day, end_day),
            )

            if not prepared:
                return 0

            aggregated: dict[tuple[str, str, str], dict[str, float | int]] = defaultdict(
                lambda: {"turnover_usd": 0.0, "trades_count": 0}
            )
            for record in prepared:
                bucket = (record.day_utc, record.platform, record.normalized_category)
                aggregated[bucket]["turnover_usd"] += record.turnover_usd
                aggregated[bucket]["trades_count"] += record.trades_count

            now = datetime.now(UTC).isoformat()
            connection.executemany(
                """
                INSERT INTO daily_volume (
                    day_utc,
                    platform,
                    normalized_category,
                    turnover_usd,
                    trades_count,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_utc, platform, normalized_category) DO UPDATE SET
                    turnover_usd = excluded.turnover_usd,
                    trades_count = excluded.trades_count,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        day_utc,
                        bucket_platform,
                        category,
                        values["turnover_usd"],
                        values["trades_count"],
                        now,
                    )
                    for (day_utc, bucket_platform, category), values in aggregated.items()
                ],
            )

        return len(aggregated)

    def list_categories(self) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT normalized_category, GROUP_CONCAT(DISTINCT platform) AS platforms
                FROM (
                    SELECT normalized_category, platform FROM daily_volume
                    UNION
                    SELECT normalized_category, platform FROM category_snapshot
                )
                GROUP BY normalized_category
                ORDER BY normalized_category ASC
                """
            ).fetchall()
        return [
            {
                "slug": row["normalized_category"],
                "platforms": sorted(set((row["platforms"] or "").split(",")) - {""}),
            }
            for row in rows
        ]

    def get_snapshot_total(self, *, platform: str, range_value: str, categories: list[str] | None) -> float | None:
        column_by_range = {
            "7d": "volume_1wk",
            "30d": "volume_1mo",
            "all": "volume_total",
        }
        column = column_by_range.get(range_value)
        if column is None:
            return None

        query = f"SELECT COALESCE(SUM({column}), 0) AS total FROM category_snapshot WHERE platform = ?"
        params: list[object] = [platform]
        if categories is not None:
            if not categories:
                return 0.0
            placeholders = ",".join("?" for _ in categories)
            query += f" AND normalized_category IN ({placeholders})"
            params.extend(categories)

        with self.database.session() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        return float(row["total"] or 0.0)

    def get_volume_rows(self, start_day: str | None, end_day: str | None, categories: list[str] | None) -> list[dict]:
        query = """
            SELECT day_utc, platform, normalized_category, turnover_usd, trades_count
            FROM daily_volume
            WHERE 1 = 1
        """
        params: list[object] = []
        if start_day is not None:
            query += " AND day_utc >= ?"
            params.append(start_day)
        if end_day is not None:
            query += " AND day_utc <= ?"
            params.append(end_day)
        if categories is not None:
            if not categories:
                return []
            placeholders = ",".join("?" for _ in categories)
            query += f" AND normalized_category IN ({placeholders})"
            params.extend(categories)
        query += " ORDER BY day_utc ASC, platform ASC"

        with self.database.session() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_date_bounds(self, categories: list[str] | None = None) -> tuple[str | None, str | None]:
        query = "SELECT MIN(day_utc) AS min_day, MAX(day_utc) AS max_day FROM daily_volume WHERE 1 = 1"
        params: list[str] = []
        if categories is not None:
            if not categories:
                return None, None
            placeholders = ",".join("?" for _ in categories)
            query += f" AND normalized_category IN ({placeholders})"
            params.extend(categories)
        with self.database.session() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None, None
        return row["min_day"], row["max_day"]

    def set_sync_state(
        self,
        *,
        platform: str,
        scope: str,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        last_cursor: str | None = None,
        partial: bool = False,
        message: str | None = None,
        stats: dict | None = None,
    ) -> None:
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO sync_state (
                    platform,
                    scope,
                    status,
                    started_at,
                    finished_at,
                    last_cursor,
                    partial,
                    message,
                    stats_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, scope) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    last_cursor = excluded.last_cursor,
                    partial = excluded.partial,
                    message = excluded.message,
                    stats_json = excluded.stats_json
                """,
                (
                    platform,
                    scope,
                    status,
                    started_at,
                    finished_at,
                    last_cursor,
                    1 if partial else 0,
                    message,
                    json.dumps(stats or {}, separators=(",", ":")),
                ),
            )

    def get_sync_states(self) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT platform, scope, status, started_at, finished_at, partial, message, stats_json
                FROM sync_state
                ORDER BY platform ASC, scope ASC
                """
            ).fetchall()
        return [
            {
                "platform": row["platform"],
                "scope": row["scope"],
                "status": row["status"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
                "partial": bool(row["partial"]),
                "message": row["message"],
                "stats": json.loads(row["stats_json"] or "{}"),
            }
            for row in rows
        ]

    def mark_running_syncs_interrupted(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE sync_state
                SET
                    status = 'interrupted',
                    finished_at = COALESCE(finished_at, ?),
                    partial = 1,
                    message = COALESCE(message, 'Previous sync was interrupted before completion')
                WHERE status = 'running'
                """,
                (now,),
            )
        return cursor.rowcount

    def get_stats(self) -> dict[str, int | str | None]:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM market_registry) AS markets_count,
                    (SELECT COUNT(*) FROM seen_trade) AS trades_count,
                    (SELECT COUNT(*) FROM daily_volume) AS daily_rows_count,
                    (SELECT MAX(day_utc) FROM daily_volume) AS latest_day
                """
            ).fetchone()
        if row is None:
            return {
                "marketsCount": 0,
                "tradesCount": 0,
                "dailyRowsCount": 0,
                "latestDay": None,
            }
        return {
            "marketsCount": row["markets_count"],
            "tradesCount": row["trades_count"],
            "dailyRowsCount": row["daily_rows_count"],
            "latestDay": row["latest_day"],
        }
