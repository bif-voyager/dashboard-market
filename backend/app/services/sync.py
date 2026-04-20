from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.clients.base import UpstreamError
from app.clients.kalshi import KalshiAdapter
from app.clients.polymarket import PolymarketAdapter
from app.services.repository import Repository
from app.utils import utc_now


class SyncService:
    def __init__(self, repository: Repository, polymarket: PolymarketAdapter, kalshi: KalshiAdapter) -> None:
        self.repository = repository
        self.polymarket = polymarket
        self.kalshi = kalshi
        self._lock = asyncio.Lock()

    async def run_sync(self, scope: str) -> dict:
        if self._lock.locked():
            return {"status": "busy", "partial": True, "results": {}}

        async with self._lock:
            results: dict[str, dict] = {}
            for platform in ("polymarket", "kalshi"):
                self.repository.set_sync_state(
                    platform=platform,
                    scope=scope,
                    status="running",
                    started_at=datetime.now(UTC).isoformat(),
                    partial=scope == "all",
                    message=None,
                    stats={},
                )

            poly_result = await self._run_platform("polymarket", scope)
            results["polymarket"] = poly_result

            kalshi_result = await self._run_platform("kalshi", scope)
            results["kalshi"] = kalshi_result

            return {
                "status": "completed",
                "partial": any(result.get("partial", False) for result in results.values()),
                "results": results,
            }

    async def _run_platform(self, platform: str, scope: str) -> dict:
        try:
            if platform == "polymarket":
                result = await self._sync_polymarket(scope)
            else:
                result = await self._sync_kalshi(scope)
            self.repository.set_sync_state(
                platform=platform,
                scope=scope,
                status="completed",
                started_at=result.get("startedAt"),
                finished_at=result.get("finishedAt"),
                partial=result.get("partial", False),
                message=result.get("message"),
                stats=result,
            )
            return result
        except UpstreamError as exc:
            result = {
                "platform": platform,
                "status": "error",
                "partial": True,
                "message": exc.message,
                "startedAt": datetime.now(UTC).isoformat(),
                "finishedAt": datetime.now(UTC).isoformat(),
            }
            self.repository.set_sync_state(
                platform=platform,
                scope=scope,
                status="error",
                started_at=result["startedAt"],
                finished_at=result["finishedAt"],
                partial=True,
                message=exc.message,
                stats=result,
            )
            return result
        except Exception as exc:  # pragma: no cover - defensive sync guard
            result = {
                "platform": platform,
                "status": "error",
                "partial": True,
                "message": str(exc),
                "startedAt": datetime.now(UTC).isoformat(),
                "finishedAt": datetime.now(UTC).isoformat(),
            }
            self.repository.set_sync_state(
                platform=platform,
                scope=scope,
                status="error",
                started_at=result["startedAt"],
                finished_at=result["finishedAt"],
                partial=True,
                message=result["message"],
                stats=result,
            )
            return result

    async def _sync_polymarket(self, scope: str) -> dict:
        started_at = datetime.now(UTC).isoformat()
        market_records, category_snapshots, market_stats = await self.polymarket.sync_markets(scope)
        markets_upserted = self.repository.upsert_markets(market_records)
        snapshots_upserted = self.repository.upsert_category_snapshots(category_snapshots)
        platform_daily_records, platform_daily_stats = await self.polymarket.sync_builder_daily_volume()
        platform_daily_rows_replaced = 0
        if platform_daily_records:
            platform_daily_rows_replaced = self.repository.replace_platform_daily_volumes(
                platform="polymarket",
                source="builder-volume",
                start_day=platform_daily_records[0].day_utc,
                end_day=platform_daily_records[-1].day_utc,
                records=platform_daily_records,
            )

        category_by_market = {
            record.market_key: record.normalized_category
            for record in market_records
        }

        def category_lookup(market_key: str) -> str | None:
            return category_by_market.get(market_key) or self.repository.get_market_category(
                "polymarket",
                market_key,
            )

        trade_records, trade_stats = await self.polymarket.sync_trades(
            scope,
            category_lookup,
            event_ids=market_stats.get("tradeCandidateEventIds") or [],
            market_keys=market_stats.get("tradeCandidateMarketKeys") or [],
        )
        trades_inserted = self.repository.record_trades(trade_records)
        finished_at = datetime.now(UTC).isoformat()

        return {
            "platform": "polymarket",
            "status": "completed",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "marketsUpserted": markets_upserted,
            "snapshotsUpserted": snapshots_upserted,
            "platformDailyRowsReplaced": platform_daily_rows_replaced,
            "tradesProcessed": len(trade_records),
            "tradesInserted": trades_inserted,
            "partial": bool(trade_stats.get("partial")) or bool(platform_daily_stats.get("partial")),
            "marketStats": market_stats,
            "platformDailyStats": platform_daily_stats,
            "tradeStats": trade_stats,
        }

    async def _sync_kalshi(self, scope: str) -> dict:
        started_at = datetime.now(UTC).isoformat()
        series_categories = await self.kalshi.fetch_series_categories()
        event_to_series, event_to_category = await self.kalshi.fetch_event_maps(scope, series_categories)
        live_market_records, live_stats = await self.kalshi.sync_live_market_registry(scope, series_categories)
        historical_market_records, historical_stats = await self.kalshi.sync_historical_market_registry(
            scope,
            series_categories,
            event_to_series,
            event_to_category,
        )
        direct_market_records = []
        direct_stats = {"pages": 0, "partial": False}
        if scope == "recent":
            direct_market_records, direct_stats = await self.kalshi.sync_recent_direct_market_registry(
                event_to_series=event_to_series,
                event_to_category=event_to_category,
                series_categories=series_categories,
            )

        market_records = direct_market_records + historical_market_records + live_market_records
        markets_upserted = self.repository.upsert_markets(market_records)

        if scope == "recent":
            ticker_categories: dict[str, str] = {}
            for record in market_records:
                current = ticker_categories.get(record.market_key)
                if current is None or (current == "uncategorized" and record.normalized_category != "uncategorized"):
                    ticker_categories[record.market_key] = record.normalized_category
            daily_records, candle_stats = await self.kalshi.sync_recent_candles(ticker_categories)
            start_day = (utc_now().date() - timedelta(days=89)).isoformat()
            end_day = utc_now().date().isoformat()
            daily_rows_replaced = self.repository.replace_daily_volumes(
                platform="kalshi",
                start_day=start_day,
                end_day=end_day,
                records=daily_records,
            )
            finished_at = datetime.now(UTC).isoformat()

            return {
                "platform": "kalshi",
                "status": "completed",
                "startedAt": started_at,
                "finishedAt": finished_at,
                "marketsUpserted": markets_upserted,
                "dailyRowsReplaced": daily_rows_replaced,
                "partial": bool(candle_stats.get("partial")) or bool(direct_stats.get("partial")),
                "seriesCount": len(series_categories),
                "liveMarketStats": live_stats,
                "historicalMarketStats": historical_stats,
                "directMarketStats": direct_stats,
                "candleStats": candle_stats,
            }

        def category_lookup(market_key: str) -> str | None:
            return self.repository.get_market_category("kalshi", market_key)

        trade_records, trade_stats = await self.kalshi.sync_trades(scope, category_lookup)
        trades_inserted = self.repository.record_trades(trade_records)
        finished_at = datetime.now(UTC).isoformat()

        return {
            "platform": "kalshi",
            "status": "completed",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "marketsUpserted": markets_upserted,
            "tradesProcessed": len(trade_records),
            "tradesInserted": trades_inserted,
            "partial": bool(trade_stats.get("partial")),
            "seriesCount": len(series_categories),
            "liveMarketStats": live_stats,
            "historicalMarketStats": historical_stats,
            "tradeStats": trade_stats,
        }
