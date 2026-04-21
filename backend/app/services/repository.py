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
    source: str = "dune-query-latest-result"
    source_query_id: int = 0


@dataclass(slots=True)
class PlatformDailyVolumeRecord:
    platform: str
    day_utc: str
    turnover_usd: float
    source: str


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def replace_daily_volumes(self, *, platform: str, records: Iterable[DailyVolumeRecord]) -> int:
        prepared = [record for record in records if record.platform == platform]
        aggregated: dict[tuple[str, str], float] = defaultdict(float)
        source_by_bucket: dict[tuple[str, str], tuple[str, int]] = {}
        for record in prepared:
            category = record.normalized_category or "all"
            bucket_key = (record.day_utc, category)
            aggregated[bucket_key] += float(record.turnover_usd)
            source_by_bucket[bucket_key] = (record.source, record.source_query_id)

        now = datetime.now(UTC).isoformat()
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM daily_volume WHERE platform = ?",
                (platform,),
            )
            if not aggregated:
                return 0

            connection.executemany(
                """
                INSERT INTO daily_volume (
                    day_utc,
                    platform,
                    normalized_category,
                    turnover_usd,
                    source,
                    source_query_id,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        day_utc,
                        platform,
                        category,
                        round(turnover_usd, 2),
                        source_by_bucket.get((day_utc, category), ("dune-query-latest-result", 0))[0],
                        source_by_bucket.get((day_utc, category), ("dune-query-latest-result", 0))[1],
                        now,
                    )
                    for (day_utc, category), turnover_usd in sorted(aggregated.items())
                ],
            )
        return len(aggregated)

    def upsert_daily_volumes(self, *, platform: str, records: Iterable[DailyVolumeRecord]) -> int:
        prepared = [record for record in records if record.platform == platform]
        if not prepared:
            return 0

        now = datetime.now(UTC).isoformat()
        with self.database.write_lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO daily_volume (
                    day_utc,
                    platform,
                    normalized_category,
                    turnover_usd,
                    source,
                    source_query_id,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_utc, platform, normalized_category) DO UPDATE SET
                    turnover_usd = excluded.turnover_usd,
                    source = excluded.source,
                    source_query_id = excluded.source_query_id,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        record.day_utc,
                        record.platform,
                        record.normalized_category or "all",
                        round(float(record.turnover_usd), 2),
                        record.source,
                        record.source_query_id,
                        now,
                    )
                    for record in prepared
                ],
            )
        return len(prepared)

    def list_categories(self) -> list[dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT normalized_category, GROUP_CONCAT(DISTINCT platform) AS platforms
                FROM daily_volume
                GROUP BY normalized_category
                ORDER BY CASE WHEN normalized_category = 'all' THEN 0 ELSE 1 END,
                         normalized_category ASC
                """
            ).fetchall()

        categories = [
            {
                "slug": row["normalized_category"],
                "platforms": sorted(set((row["platforms"] or "").split(",")) - {""}),
            }
            for row in rows
        ]
        if not categories:
            categories.insert(0, {"slug": "all", "platforms": ["polymarket", "kalshi"]})
        return categories

    def get_volume_rows(
        self,
        start_day: str | None,
        end_day: str | None,
        categories: list[str] | None,
        platform: str | None = None,
    ) -> list[dict]:
        query = """
            SELECT day_utc, platform, normalized_category, turnover_usd, source, source_query_id
            FROM daily_volume
            WHERE 1 = 1
        """
        params: list[object] = []
        if platform is not None:
            query += " AND platform = ?"
            params.append(platform)
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
        params: list[object] = []
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

    def get_platform_date_bounds(
        self,
        platform: str,
        categories: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        query = "SELECT MIN(day_utc) AS min_day, MAX(day_utc) AS max_day FROM daily_volume WHERE platform = ?"
        params: list[object] = [platform]
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

    def get_platform_sources(self) -> dict[str, dict]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT platform,
                       GROUP_CONCAT(DISTINCT source) AS sources,
                       GROUP_CONCAT(DISTINCT source_query_id) AS query_ids,
                       MIN(day_utc) AS min_day,
                       MAX(day_utc) AS max_day,
                       COUNT(*) AS rows_count
                FROM daily_volume
                GROUP BY platform
                """
            ).fetchall()
        return {
            row["platform"]: {
                "sources": sorted(set((row["sources"] or "").split(",")) - {""}),
                "queryIds": sorted(set((row["query_ids"] or "").split(",")) - {""}),
                "minDay": row["min_day"],
                "maxDay": row["max_day"],
                "rowsCount": row["rows_count"],
            }
            for row in rows
        }

    def get_platform_days(self, start_day: str, end_day: str) -> dict[str, set[str]]:
        with self.database.session() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT platform, day_utc
                FROM daily_volume
                WHERE day_utc >= ? AND day_utc <= ?
                ORDER BY platform ASC, day_utc ASC
                """,
                (start_day, end_day),
            ).fetchall()

        days_by_platform: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            days_by_platform[row["platform"]].add(row["day_utc"])
        return days_by_platform

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
                    COUNT(*) AS daily_rows_count,
                    COUNT(DISTINCT normalized_category) AS categories_count,
                    MAX(day_utc) AS latest_day
                FROM daily_volume
                """
            ).fetchone()
        if row is None:
            return {
                "marketsCount": 0,
                "tradesCount": 0,
                "dailyRowsCount": 0,
                "platformDailyRowsCount": 0,
                "categoriesCount": 0,
                "latestDay": None,
            }
        return {
            "marketsCount": 0,
            "tradesCount": 0,
            "dailyRowsCount": row["daily_rows_count"],
            "platformDailyRowsCount": 0,
            "categoriesCount": row["categories_count"],
            "latestDay": row["latest_day"],
        }
