from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from app.clients.base import PublicApiClient
from app.config import Settings
from app.services.repository import DailyVolumeRecord, MarketRecord
from app.utils import (
    coerce_timestamp,
    day_from_timestamp,
    kalshi_candlestick_turnover_usd,
    kalshi_turnover_usd,
    normalize_category,
    utc_now,
)


class KalshiAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = PublicApiClient(
            base_url=settings.kalshi_base_url,
            source="kalshi",
            timeout_seconds=settings.request_timeout_seconds,
            min_interval_seconds=settings.kalshi_request_spacing_seconds,
        )

    async def close(self) -> None:
        await self.client.close()

    async def fetch_series_categories(self) -> dict[str, str]:
        payload = await self.client.get_json("/series")
        series = payload.get("series", [])
        return {
            str(item.get("ticker")): normalize_category(item.get("category"))
            for item in series
            if item.get("ticker")
        }

    async def sync_historical_market_registry(
        self,
        scope: str,
        series_categories: dict[str, str],
        event_to_series: dict[str, str],
        event_to_category: dict[str, str],
    ) -> tuple[list[MarketRecord], dict]:
        cursor: str | None = None
        page_count = 0
        max_pages = (
            self.settings.kalshi_historical_market_bootstrap_max_pages
            if scope == "all"
            else self.settings.kalshi_historical_market_recent_max_pages
        )
        records: list[MarketRecord] = []
        recent_cutoff = utc_now() - timedelta(days=90) if scope != "all" else None
        skipped_older = 0
        markets_scanned = 0
        stats = {
            "pages": 0,
            "marketsScanned": 0,
            "records": 0,
            "skippedOlderThanRecentWindow": 0,
            "partial": False,
            "minDay": None,
            "maxDay": None,
        }

        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/historical/markets", params=params)
            markets = payload.get("markets", [])
            if not markets:
                break
            page_count += 1
            markets_scanned += len(markets)
            for market in markets:
                if recent_cutoff is not None and not self._historical_market_in_recent_window(market, recent_cutoff):
                    skipped_older += 1
                    continue
                volume_fp = float(market.get("volume_fp") or 0)
                volume_24h_fp = float(market.get("volume_24h_fp") or 0)
                if volume_fp <= 0 and volume_24h_fp <= 0:
                    continue
                event_key = str(market.get("event_ticker")) if market.get("event_ticker") else None
                series_key = event_to_series.get(event_key or "")
                category = series_categories.get(series_key or "") or event_to_category.get(event_key or "") or "uncategorized"
                ticker = market.get("ticker")
                if not ticker:
                    continue
                min_day, max_day = self._extract_market_date_bounds(market)
                self._merge_date_bounds(stats, min_day, max_day)
                records.append(
                    MarketRecord(
                        platform="kalshi",
                        market_key=str(ticker),
                        event_key=event_key,
                        series_key=series_key,
                        title=market.get("title"),
                        raw_category=category,
                        normalized_category=category,
                        source="historical-markets",
                    )
                )
            cursor = payload.get("cursor")
            if not cursor:
                break

        stats["pages"] = page_count
        stats["marketsScanned"] = markets_scanned
        stats["records"] = len(records)
        stats["skippedOlderThanRecentWindow"] = skipped_older
        stats["partial"] = bool(cursor) and page_count >= max_pages
        return records, stats

    async def sync_direct_market_registry(
        self,
        scope: str,
        *,
        event_to_series: dict[str, str],
        event_to_category: dict[str, str],
        series_categories: dict[str, str],
    ) -> tuple[list[MarketRecord], dict]:
        end_at = utc_now()
        start_at = end_at - timedelta(days=90)
        max_pages = (
            self.settings.kalshi_direct_market_bootstrap_max_pages
            if scope == "all"
            else self.settings.kalshi_direct_market_recent_max_pages
        )
        records_by_ticker: dict[str, MarketRecord] = {}
        stats = {
            "statuses": {},
            "marketsScanned": 0,
            "volumePositiveMarkets": 0,
            "pages": 0,
            "partial": False,
            "minDay": None,
            "maxDay": None,
        }

        if scope == "all":
            query_specs: list[tuple[str, dict[str, str | int]]] = [
                ("open", {"status": "open"}),
                ("closed", {"status": "closed"}),
                ("settled", {"status": "settled"}),
            ]
        else:
            query_specs = [
                ("open", {"status": "open"}),
                (
                    "closed",
                    {
                        "status": "closed",
                        "min_close_ts": int(start_at.timestamp()),
                        "max_close_ts": int(end_at.timestamp()),
                    },
                ),
                (
                    "settled",
                    {
                        "status": "settled",
                        "min_settled_ts": int(start_at.timestamp()),
                        "max_settled_ts": int(end_at.timestamp()),
                    },
                ),
            ]

        for status_key, base_params in query_specs:
            status_records, status_stats = await self._fetch_direct_markets(
                base_params=base_params,
                max_pages=max_pages,
                event_to_series=event_to_series,
                event_to_category=event_to_category,
                series_categories=series_categories,
            )
            for record in status_records:
                current = records_by_ticker.get(record.market_key)
                if current is None or (
                    current.normalized_category == "uncategorized"
                    and record.normalized_category != "uncategorized"
                ):
                    records_by_ticker[record.market_key] = record
            stats["statuses"][status_key] = status_stats
            stats["marketsScanned"] += status_stats["marketsScanned"]
            stats["volumePositiveMarkets"] += status_stats["volumePositiveMarkets"]
            stats["pages"] += status_stats["pages"]
            stats["partial"] = bool(stats["partial"]) or bool(status_stats["partial"])
            self._merge_date_bounds(stats, status_stats.get("minDay"), status_stats.get("maxDay"))

        stats["records"] = len(records_by_ticker)
        return list(records_by_ticker.values()), stats

    async def _fetch_direct_markets(
        self,
        *,
        base_params: dict[str, str | int],
        max_pages: int,
        event_to_series: dict[str, str],
        event_to_category: dict[str, str],
        series_categories: dict[str, str],
    ) -> tuple[list[MarketRecord], dict]:
        cursor: str | None = None
        page_count = 0
        records: list[MarketRecord] = []
        markets_scanned = 0
        volume_positive = 0
        stats = {
            "pages": 0,
            "marketsScanned": 0,
            "volumePositiveMarkets": 0,
            "records": 0,
            "partial": False,
            "minDay": None,
            "maxDay": None,
        }

        for _ in range(max_pages):
            params = {"limit": 1000, **base_params}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/markets", params=params)
            markets = payload.get("markets", [])
            if not markets:
                break
            page_count += 1
            markets_scanned += len(markets)
            for market in markets:
                ticker = market.get("ticker")
                if not ticker:
                    continue
                volume_fp = float(market.get("volume_fp") or 0)
                volume_24h_fp = float(market.get("volume_24h_fp") or 0)
                if volume_fp <= 0 and volume_24h_fp <= 0:
                    continue

                volume_positive += 1
                event_key = str(market.get("event_ticker")) if market.get("event_ticker") else None
                series_key = event_to_series.get(event_key or "")
                category = (
                    series_categories.get(series_key or "")
                    or event_to_category.get(event_key or "")
                    or "uncategorized"
                )
                min_day, max_day = self._extract_market_date_bounds(market)
                self._merge_date_bounds(stats, min_day, max_day)
                records.append(
                    MarketRecord(
                        platform="kalshi",
                        market_key=str(ticker),
                        event_key=event_key,
                        series_key=series_key,
                        title=market.get("title"),
                        raw_category=category,
                        normalized_category=category,
                        source=f"markets-{base_params.get('status')}",
                    )
                )

            cursor = payload.get("cursor")
            if not cursor:
                break

        stats["pages"] = page_count
        stats["marketsScanned"] = markets_scanned
        stats["volumePositiveMarkets"] = volume_positive
        stats["records"] = len(records)
        stats["partial"] = bool(cursor) and page_count >= max_pages
        return records, stats

    async def fetch_event_maps(
        self,
        scope: str,
        series_categories: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str], dict]:
        cursor: str | None = None
        event_to_series: dict[str, str] = {}
        event_to_category: dict[str, str] = {}
        max_pages = (
            self.settings.kalshi_event_bootstrap_max_pages
            if scope == "all"
            else self.settings.kalshi_event_recent_max_pages
        )
        page_count = 0
        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/events", params=params)
            events = payload.get("events", [])
            if not events:
                break
            page_count += 1
            for event in events:
                event_key = event.get("event_ticker")
                series_key = event.get("series_ticker")
                if not event_key or not series_key:
                    continue
                event_to_series[str(event_key)] = str(series_key)
                event_to_category[str(event_key)] = series_categories.get(
                    str(series_key),
                    normalize_category(event.get("category")),
                )
            cursor = payload.get("cursor")
            if not cursor:
                break
        return event_to_series, event_to_category, {
            "pages": page_count,
            "records": len(event_to_series),
            "partial": bool(cursor) and page_count >= max_pages,
        }

    async def fetch_cutoff(self) -> dict:
        return await self.client.get_json("/historical/cutoff")

    async def sync_recent_candles(
        self,
        ticker_categories: dict[str, str],
        *,
        historical_tickers: set[str] | None = None,
    ) -> tuple[list[DailyVolumeRecord], dict]:
        end_day = utc_now().date()
        start_day = end_day - timedelta(days=89)
        return await self.sync_candles(
            ticker_categories,
            start_day=start_day.isoformat(),
            end_day=end_day.isoformat(),
            historical_tickers=historical_tickers,
        )

    async def sync_candles(
        self,
        ticker_categories: dict[str, str],
        *,
        start_day: str,
        end_day: str,
        historical_tickers: set[str] | None = None,
    ) -> tuple[list[DailyVolumeRecord], dict]:
        if not ticker_categories:
            return [], {
                "chunks": 0,
                "tickers": 0,
                "marketsReturned": 0,
                "candlesProcessed": 0,
                "startDay": start_day,
                "endDay": end_day,
                "periodIntervalMinutes": 1440,
                "partial": False,
            }

        start_date = date.fromisoformat(start_day)
        end_date = date.fromisoformat(end_day)
        if start_date > end_date:
            return [], {
                "chunks": 0,
                "tickers": len(ticker_categories),
                "marketsReturned": 0,
                "candlesProcessed": 0,
                "startDay": start_day,
                "endDay": end_day,
                "periodIntervalMinutes": 1440,
                "partial": False,
                "skipped": True,
            }

        start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
        end_at = datetime.combine(end_date, time.max, tzinfo=UTC)
        cutoff_payload = await self.fetch_cutoff()
        market_cutoff = coerce_timestamp(cutoff_payload.get("market_settled_ts"))
        historical_ticker_set = set(historical_tickers or set())
        if start_at < market_cutoff:
            archived_tickers = sorted(set(ticker_categories) & historical_ticker_set)
        else:
            archived_tickers = []
        live_tickers = sorted(set(ticker_categories) - set(archived_tickers))
        span_days = (end_date - start_date).days + 1
        if span_days > 180:
            chunk_size = max(20, self.settings.kalshi_candlestick_chunk_size // 4)
            max_parallel = max(1, self.settings.fetch_concurrency)
        else:
            chunk_size = self.settings.kalshi_candlestick_chunk_size
            max_parallel = min(6, max(2, self.settings.fetch_concurrency * 2))
        semaphore = asyncio.Semaphore(max_parallel)
        aggregated: dict[tuple[str, str], float] = defaultdict(float)
        stats = {
            "chunks": 0,
            "requests": 0,
            "liveRequests": 0,
            "historicalRequests": 0,
            "tickers": len(ticker_categories),
            "liveTickers": len(live_tickers),
            "historicalTickers": len(archived_tickers),
            "marketsReturned": 0,
            "liveMarketsReturned": 0,
            "historicalMarketsReturned": 0,
            "candlesProcessed": 0,
            "startDay": start_day,
            "endDay": end_day,
            "periodIntervalMinutes": 1440,
            "marketCutoff": market_cutoff.isoformat(),
            "partial": False,
            "failedChunks": 0,
            "failedTickers": [],
            "spanDays": span_days,
        }

        async def fetch_chunk(chunk: list[str]) -> list[dict]:
            params = {
                "market_tickers": ",".join(chunk),
                "start_ts": int(start_at.timestamp()),
                "end_ts": int(end_at.timestamp()),
                "period_interval": 1440,
            }
            async with semaphore:
                stats["requests"] += 1
                stats["liveRequests"] += 1
                payload = await self.client.get_json("/markets/candlesticks", params=params)
            return payload.get("markets", [])

        async def fetch_chunk_resilient(chunk: list[str]) -> list[dict]:
            try:
                return await fetch_chunk(chunk)
            except Exception:
                if len(chunk) == 1:
                    stats["partial"] = True
                    stats["failedChunks"] += 1
                    failed_tickers = stats["failedTickers"]
                    if isinstance(failed_tickers, list):
                        failed_tickers.append(chunk[0])
                    return []

                midpoint = len(chunk) // 2
                left, right = await asyncio.gather(
                    fetch_chunk_resilient(chunk[:midpoint]),
                    fetch_chunk_resilient(chunk[midpoint:]),
                )
                return left + right

        async def fetch_historical_ticker(ticker: str) -> dict | None:
            params = {
                "start_ts": int(start_at.timestamp()),
                "end_ts": int(end_at.timestamp()),
                "period_interval": 1440,
            }
            try:
                async with semaphore:
                    stats["requests"] += 1
                    stats["historicalRequests"] += 1
                    return await self.client.get_json(f"/historical/markets/{ticker}/candlesticks", params=params)
            except Exception:
                stats["partial"] = True
                failed_tickers = stats["failedTickers"]
                if isinstance(failed_tickers, list):
                    failed_tickers.append(ticker)
                return None

        def add_candles(ticker: str, candles: list[dict]) -> None:
            category = ticker_categories.get(ticker) or "uncategorized"
            for candle in candles:
                turnover = float(kalshi_candlestick_turnover_usd(candle))
                if turnover <= 0:
                    continue
                stats["candlesProcessed"] += 1
                day_key = day_from_timestamp(candle.get("end_period_ts"))
                aggregated[(day_key, category)] += turnover

        chunks = [live_tickers[index : index + chunk_size] for index in range(0, len(live_tickers), chunk_size)]
        stats["chunks"] = len(chunks)
        results = await asyncio.gather(*(fetch_chunk_resilient(chunk) for chunk in chunks))

        for markets in results:
            stats["marketsReturned"] += len(markets)
            stats["liveMarketsReturned"] += len(markets)
            for market in markets:
                ticker = str(market.get("market_ticker"))
                add_candles(ticker, market.get("candlesticks", []) or [])

        historical_results = await asyncio.gather(*(fetch_historical_ticker(ticker) for ticker in archived_tickers))
        for payload in historical_results:
            if not payload:
                continue
            ticker = str(payload.get("ticker") or "")
            if not ticker:
                continue
            stats["marketsReturned"] += 1
            stats["historicalMarketsReturned"] += 1
            add_candles(ticker, payload.get("candlesticks", []) or [])

        records = [
            DailyVolumeRecord(
                platform="kalshi",
                day_utc=day_key,
                normalized_category=category,
                turnover_usd=round(turnover, 2),
            )
            for (day_key, category), turnover in aggregated.items()
        ]

        return records, stats

    def _merge_date_bounds(self, stats: dict, min_day: str | None, max_day: str | None) -> None:
        if min_day and (stats.get("minDay") is None or min_day < stats["minDay"]):
            stats["minDay"] = min_day
        if max_day and (stats.get("maxDay") is None or max_day > stats["maxDay"]):
            stats["maxDay"] = max_day

    def _extract_market_date_bounds(self, *payloads: dict | None) -> tuple[str | None, str | None]:
        candidates: list[str] = []
        for payload in payloads:
            if not payload:
                continue
            for key in (
                "created_time",
                "open_time",
                "open_date",
                "start_date",
                "close_time",
                "latest_expiration_time",
                "expiration_time",
                "settlement_time",
                "settled_time",
                "result_time",
            ):
                value = payload.get(key)
                if not value:
                    continue
                try:
                    candidates.append(day_from_timestamp(value))
                except (TypeError, ValueError):
                    continue
        if not candidates:
            return None, None
        return min(candidates), max(candidates)

    def _historical_market_in_recent_window(self, market: dict, recent_cutoff: datetime) -> bool:
        for key in ("close_time", "latest_expiration_time", "created_time"):
            value = market.get(key)
            if value:
                return coerce_timestamp(value) >= recent_cutoff
        return True

    async def sync_daily_trade_backfill(
        self,
        *,
        day_utc: str,
        category_lookup: callable,
    ) -> tuple[list[DailyVolumeRecord], dict]:
        day_date = date.fromisoformat(day_utc)
        start_at = datetime.combine(day_date, time.min, tzinfo=UTC)
        end_at = datetime.combine(day_date, time.max, tzinfo=UTC)
        cutoff_payload = await self.fetch_cutoff()
        cutoff_dt = coerce_timestamp(cutoff_payload.get("trades_created_ts"))
        paths: list[str] = []
        if start_at < cutoff_dt:
            paths.append("/historical/trades")
        if end_at > cutoff_dt:
            paths.append("/markets/trades")

        aggregated: dict[tuple[str, str], dict[str, float | int]] = defaultdict(
            lambda: {"turnover_usd": 0.0, "trades_count": 0}
        )
        category_cache: dict[str, str] = {}
        stats = {
            "day": day_utc,
            "pages": 0,
            "tradesProcessed": 0,
            "partial": False,
            "paths": paths,
            "maxPagesPerPath": self.settings.kalshi_backfill_trade_day_max_pages,
        }

        for path in paths:
            cursor: str | None = None
            pages_for_path = 0
            while pages_for_path < self.settings.kalshi_backfill_trade_day_max_pages:
                params: dict[str, str | int] = {
                    "limit": min(self.settings.kalshi_page_limit, 1000),
                    "min_ts": int(start_at.timestamp()),
                    "max_ts": int(end_at.timestamp()),
                }
                if cursor:
                    params["cursor"] = cursor
                payload = await self.client.get_json(path, params=params)
                batch = payload.get("trades", [])
                if not batch:
                    break

                pages_for_path += 1
                stats["pages"] += 1
                for trade in batch:
                    ticker = str(trade.get("ticker"))
                    if ticker not in category_cache:
                        category_cache[ticker] = category_lookup(ticker) or "uncategorized"
                    day_key = day_from_timestamp(trade.get("created_time"))
                    bucket = aggregated[(day_key, category_cache[ticker])]
                    bucket["turnover_usd"] += float(kalshi_turnover_usd(trade))
                    bucket["trades_count"] += 1
                    stats["tradesProcessed"] += 1

                cursor = payload.get("cursor")
                if not cursor:
                    break
            stats["partial"] = bool(stats["partial"]) or bool(cursor)

        records = [
            DailyVolumeRecord(
                platform="kalshi",
                day_utc=day_key,
                normalized_category=category,
                turnover_usd=round(float(values["turnover_usd"]), 2),
                trades_count=int(values["trades_count"]),
            )
            for (day_key, category), values in aggregated.items()
        ]
        return records, stats
