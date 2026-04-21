from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from app.clients.base import UpstreamError
from app.clients.dune import DuneClient, DuneQueryResult
from app.config import Settings
from app.services.dune_volume import records_from_dune_rows
from app.services.repository import DailyVolumeRecord, Repository


KALSHI_TRADE_REPORT_FALLBACK_SOURCE = "dune-sql-kalshi-trade-report-fallback"


class SyncService:
    def __init__(self, settings: Settings, repository: Repository, dune: DuneClient) -> None:
        self.settings = settings
        self.repository = repository
        self.dune = dune
        self._lock = asyncio.Lock()

    async def run_sync(self, scope: str, platform: str | None = None) -> dict:
        if self._lock.locked():
            return {"status": "busy", "partial": True, "results": {}}

        async with self._lock:
            platforms = (platform,) if platform else ("polymarket", "kalshi")
            for platform_name in platforms:
                self.repository.set_sync_state(
                    platform=platform_name,
                    scope=scope,
                    status="running",
                    started_at=datetime.now(UTC).isoformat(),
                    partial=True,
                    message=None,
                    stats={},
                )

            results: dict[str, dict] = {}
            for platform_name in platforms:
                results[platform_name] = await self._run_platform(platform_name, scope)

            return {
                "status": "completed",
                "partial": any(result.get("partial", False) for result in results.values()),
                "results": results,
            }

    async def _run_platform(self, platform: str, scope: str) -> dict:
        started_at = datetime.now(UTC).isoformat()
        try:
            query_id = self._query_id_for_platform(platform)
            result = await self.dune.get_latest_result(query_id)
            records = records_from_dune_rows(
                platform=platform,
                query_id=query_id,
                rows=result.rows,
            )
            fallback: dict = {}
            if platform == "kalshi":
                records, fallback = await self._with_kalshi_trade_report_fallback(records)
            rows_written = self.repository.replace_daily_volumes(platform=platform, records=records)
            finished_at = datetime.now(UTC).isoformat()
            payload = self._build_success_payload(
                platform=platform,
                scope=scope,
                started_at=started_at,
                finished_at=finished_at,
                result=result,
                records=records,
                rows_written=rows_written,
                fallback=fallback,
            )
            self.repository.set_sync_state(
                platform=platform,
                scope=scope,
                status="completed",
                started_at=started_at,
                finished_at=finished_at,
                partial=payload["partial"],
                message=payload.get("message"),
                stats=payload,
            )
            return payload
        except UpstreamError as exc:
            return self._record_error(platform=platform, scope=scope, started_at=started_at, message=exc.message)
        except Exception as exc:  # pragma: no cover - defensive sync guard
            return self._record_error(platform=platform, scope=scope, started_at=started_at, message=str(exc))

    def _query_id_for_platform(self, platform: str) -> int:
        if platform == "polymarket":
            return self.settings.dune_polymarket_query_id
        if platform == "kalshi":
            return self.settings.dune_kalshi_query_id
        raise ValueError(f"Unsupported platform: {platform}")

    async def _with_kalshi_trade_report_fallback(
        self,
        records: list[DailyVolumeRecord],
    ) -> tuple[list[DailyVolumeRecord], dict]:
        if not self.settings.kalshi_trade_report_fallback_enabled:
            return records, {}

        configured_days = self._configured_kalshi_fallback_days()
        if not configured_days or not records:
            return records, {}

        record_days = {record.day_utc for record in records}
        min_day = min(record_days)
        max_day = max(record_days)
        fallback_days = [
            day
            for day in configured_days
            if min_day <= day <= max_day
        ]
        if not fallback_days:
            return records, {}

        try:
            result = await self.dune.execute_sql(self._kalshi_trade_report_fallback_sql(fallback_days))
            fallback_records = records_from_dune_rows(
                platform="kalshi",
                query_id=0,
                rows=result.rows,
                source=KALSHI_TRADE_REPORT_FALLBACK_SOURCE,
            )
        except UpstreamError as exc:
            return records, {
                "attempted": True,
                "status": "error",
                "fallbackDays": fallback_days,
                "missingDays": sorted(day for day in fallback_days if day not in record_days),
                "message": exc.message,
            }

        filled_days = sorted({record.day_utc for record in fallback_records})
        fallback_day_set = set(fallback_days)
        retained_records = [record for record in records if record.day_utc not in fallback_day_set]
        return retained_records + fallback_records, {
            "attempted": True,
            "status": "completed",
            "fallbackDays": fallback_days,
            "missingDays": sorted(day for day in fallback_days if day not in record_days),
            "replacedDays": sorted(day for day in fallback_days if day in record_days),
            "filledDays": filled_days,
            "rowsNormalized": len(fallback_records),
            "executionId": result.execution_id,
            "source": KALSHI_TRADE_REPORT_FALLBACK_SOURCE,
            "volumeFormula": "SUM(contracts_traded)",
            "categoryMap": "kalshi.market_report ticker_name -> category",
        }

    def _configured_kalshi_fallback_days(self) -> list[str]:
        days: list[str] = []
        for raw_day in self.settings.kalshi_trade_report_fallback_days.split(","):
            cleaned = raw_day.strip()
            if not cleaned:
                continue
            days.append(date.fromisoformat(cleaned).isoformat())
        return sorted(set(days))

    def _kalshi_trade_report_fallback_sql(self, days: list[str]) -> str:
        day_values = ", ".join(f"(DATE '{day}')" for day in days)
        return f"""
WITH fallback_days(day) AS (
    VALUES {day_values}
),
trades AS (
    SELECT
        CAST(t.date AS DATE) AS day,
        t.ticker_name,
        SUM(t.contracts_traded) AS daily_volume_usd
    FROM kalshi.trade_report t
    INNER JOIN fallback_days fd
        ON CAST(t.date AS DATE) = fd.day
    GROUP BY 1, 2
),
category_map AS (
    SELECT
        ticker_name,
        MAX(category) AS category
    FROM kalshi.market_report
    WHERE category IS NOT NULL
      AND TRIM(category) <> ''
    GROUP BY 1
)
SELECT
    day,
    COALESCE(LOWER(TRIM(category_map.category)), 'uncategorized') AS category,
    SUM(trades.daily_volume_usd) AS daily_volume_usd
FROM trades
LEFT JOIN category_map
    ON category_map.ticker_name = trades.ticker_name
GROUP BY 1, 2
ORDER BY 1, 2
"""

    def _build_success_payload(
        self,
        *,
        platform: str,
        scope: str,
        started_at: str,
        finished_at: str,
        result: DuneQueryResult,
        records: list[DailyVolumeRecord],
        rows_written: int,
        fallback: dict,
    ) -> dict:
        days = [record.day_utc for record in records]
        categories = sorted({record.normalized_category for record in records})
        fallback_failed = bool(fallback) and fallback.get("status") == "error"
        partial = rows_written == 0 or fallback_failed
        message = None if rows_written else f"Dune query {result.query_id} returned no daily volume rows"
        if fallback_failed:
            message = fallback.get("message") or "Kalshi trade-report fallback failed"
        return {
            "platform": platform,
            "scope": scope,
            "status": "completed",
            "source": "dune-query-latest-result",
            "queryId": result.query_id,
            "executionId": result.execution_id,
            "executionState": result.state,
            "submittedAt": result.submitted_at,
            "expiresAt": result.expires_at,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "rowsFetched": len(result.rows),
            "rowsNormalized": len(records),
            "dailyRowsWritten": rows_written,
            "categories": categories,
            "minDay": min(days) if days else None,
            "maxDay": max(days) if days else None,
            "pages": result.pages,
            "metadata": result.metadata,
            "fallback": fallback,
            "partial": partial,
            "message": message,
        }

    def _record_error(self, *, platform: str, scope: str, started_at: str, message: str) -> dict:
        finished_at = datetime.now(UTC).isoformat()
        payload = {
            "platform": platform,
            "scope": scope,
            "status": "error",
            "source": "dune-query-latest-result",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "partial": True,
            "message": message,
        }
        self.repository.set_sync_state(
            platform=platform,
            scope=scope,
            status="error",
            started_at=started_at,
            finished_at=finished_at,
            partial=True,
            message=message,
            stats=payload,
        )
        return payload
