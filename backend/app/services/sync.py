from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

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

    async def run_sync(self, scope: str, platform: str | None = None) -> dict:
        if self._lock.locked():
            return {"status": "busy", "partial": True, "results": {}}

        async with self._lock:
            platforms = (platform,) if platform else ("polymarket", "kalshi")
            results: dict[str, dict] = {}
            for platform_name in platforms:
                self.repository.set_sync_state(
                    platform=platform_name,
                    scope=scope,
                    status="running",
                    started_at=datetime.now(UTC).isoformat(),
                    partial=scope == "all",
                    message=None,
                    stats={},
                )

            for platform_name in platforms:
                results[platform_name] = await self._run_platform(platform_name, scope)

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
        if scope == "recent":
            series_categories = await self.kalshi.fetch_series_categories()
            event_to_series, event_to_category, event_stats = await self.kalshi.fetch_event_maps(
                scope,
                series_categories,
            )
            historical_market_records, historical_stats = await self.kalshi.sync_historical_market_registry(
                scope,
                series_categories,
                event_to_series,
                event_to_category,
            )
            direct_market_records, direct_stats = await self.kalshi.sync_direct_market_registry(
                scope,
                event_to_series=event_to_series,
                event_to_category=event_to_category,
                series_categories=series_categories,
            )

            market_records = direct_market_records + historical_market_records
            markets_upserted = self.repository.upsert_markets(market_records)
            ticker_categories: dict[str, str] = {}
            for record in market_records:
                current = ticker_categories.get(record.market_key)
                if current is None or (current == "uncategorized" and record.normalized_category != "uncategorized"):
                    ticker_categories[record.market_key] = record.normalized_category
            historical_tickers = {
                record.market_key
                for record in historical_market_records
                if record.market_key
            }
            daily_records, candle_stats = await self.kalshi.sync_recent_candles(
                ticker_categories,
                historical_tickers=historical_tickers,
            )
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
                "partial": bool(event_stats.get("partial"))
                or bool(historical_stats.get("partial"))
                or bool(direct_stats.get("partial"))
                or bool(candle_stats.get("partial")),
                "seriesCount": len(series_categories),
                "eventMapStats": event_stats,
                "historicalMarketStats": historical_stats,
                "directMarketStats": direct_stats,
                "candleStats": candle_stats,
            }

        backfill_start_day, backfill_end_day = self._resolve_kalshi_all_backfill_window()
        message = None
        trade_stats = {
            "startDay": backfill_start_day,
            "endDay": backfill_end_day,
            "partial": False,
            "skipped": backfill_start_day is None or backfill_end_day is None,
            "chunksRequested": 0,
            "chunksCompleted": 0,
            "livePages": 0,
            "historicalPages": 0,
            "liveWindows": 0,
            "historicalWindows": 0,
            "dailyRowsReplaced": 0,
            "tradesProcessed": 0,
            "pages": 0,
        }
        daily_rows_replaced = 0
        trades_processed = 0
        if backfill_start_day and backfill_end_day:
            def category_lookup(market_key: str) -> str | None:
                return self.repository.get_market_category("kalshi", market_key)

            for chunk_start_day, chunk_end_day in self._iter_descending_backfill_chunks(
                start_day=backfill_start_day,
                end_day=backfill_end_day,
            ):
                trade_stats["chunksRequested"] += 1
                chunk_records, chunk_stats = await self.kalshi.sync_daily_trade_backfill(
                    day_utc=chunk_start_day,
                    category_lookup=category_lookup,
                )
                trades_processed += int(chunk_stats.get("tradesProcessed", 0))
                daily_rows_replaced += self.repository.replace_daily_volumes(
                    platform="kalshi",
                    start_day=chunk_start_day,
                    end_day=chunk_end_day,
                    records=chunk_records,
                )
                trade_stats["chunksCompleted"] += 1
                trade_stats["dailyRowsReplaced"] = daily_rows_replaced
                trade_stats["tradesProcessed"] = trades_processed
                trade_stats["pages"] += int(chunk_stats.get("pages", 0))
                trade_stats["partial"] = bool(trade_stats["partial"]) or bool(chunk_stats.get("partial"))
                self.repository.set_sync_state(
                    platform="kalshi",
                    scope="all",
                    status="running",
                    started_at=started_at,
                    partial=True,
                    stats={
                        "platform": "kalshi",
                        "status": "running",
                        "startedAt": started_at,
                        "tradeStats": trade_stats,
                    },
                )
        else:
            message = "Kalshi all-time backfill is already materialized for the current leading edge."
        finished_at = datetime.now(UTC).isoformat()

        return {
            "platform": "kalshi",
            "status": "completed",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "message": message,
            "marketsUpserted": 0,
            "dailyRowsReplaced": daily_rows_replaced,
            "tradesProcessed": trades_processed,
            "partial": bool(trade_stats.get("partial")),
            "tradeStats": trade_stats,
        }

    def _resolve_kalshi_all_backfill_window(self) -> tuple[str | None, str | None]:
        existing_min_day, _ = self.repository.get_daily_platform_date_bounds("kalshi")
        if not existing_min_day:
            return None, None

        existing_min = date.fromisoformat(existing_min_day)
        backfill_end_day = (existing_min - timedelta(days=1)).isoformat()
        backfill_start_day = (existing_min - timedelta(days=self.kalshi.settings.kalshi_all_backfill_lookback_days)).isoformat()
        if date.fromisoformat(backfill_start_day) > date.fromisoformat(backfill_end_day):
            return None, None
        return backfill_start_day, backfill_end_day

    def _iter_descending_backfill_chunks(
        self,
        *,
        start_day: str,
        end_day: str,
        chunk_days: int = 1,
    ) -> list[tuple[str, str]]:
        start_date = date.fromisoformat(start_day)
        end_date = date.fromisoformat(end_day)
        chunks: list[tuple[str, str]] = []
        cursor_end = end_date
        while cursor_end >= start_date:
            chunk_start = max(start_date, cursor_end - timedelta(days=chunk_days - 1))
            chunks.append((chunk_start.isoformat(), cursor_end.isoformat()))
            cursor_end = chunk_start - timedelta(days=1)
        return chunks
