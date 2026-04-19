from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime, time, timedelta

from app.clients.base import PublicApiClient
from app.config import Settings
from app.services.repository import DailyVolumeRecord, MarketRecord, TradeRecord
from app.utils import (
    coerce_timestamp,
    day_from_timestamp,
    kalshi_candlestick_turnover_usd,
    kalshi_turnover_usd,
    normalize_category,
    stable_trade_key,
    utc_now,
)


class KalshiAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = PublicApiClient(
            base_url=settings.kalshi_base_url,
            source="kalshi",
            timeout_seconds=settings.request_timeout_seconds,
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

    async def sync_live_market_registry(self, scope: str, series_categories: dict[str, str]) -> tuple[list[MarketRecord], dict]:
        cursor: str | None = None
        page_count = 0
        max_pages = (
            self.settings.kalshi_event_bootstrap_max_pages
            if scope == "all"
            else self.settings.kalshi_event_recent_max_pages
        )
        records: list[MarketRecord] = []

        for _ in range(max_pages):
            params: dict[str, str | int | bool] = {
                "limit": 200,
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/events", params=params)
            events = payload.get("events", [])
            if not events:
                break
            page_count += 1
            for event in events:
                series_key = str(event.get("series_ticker")) if event.get("series_ticker") else None
                raw_category = event.get("category")
                category = series_categories.get(series_key or "", normalize_category(raw_category))
                for market in event.get("markets", []) or []:
                    ticker = market.get("ticker")
                    if not ticker:
                        continue
                    records.append(
                        MarketRecord(
                            platform="kalshi",
                            market_key=str(ticker),
                            event_key=str(event.get("event_ticker")) if event.get("event_ticker") else None,
                            series_key=series_key,
                            title=market.get("title") or event.get("title"),
                            raw_category=raw_category,
                            normalized_category=category,
                            source="events-live",
                        )
                    )
            cursor = payload.get("cursor")
            if not cursor:
                break
        return records, {"pages": page_count}

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

        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/historical/markets", params=params)
            markets = payload.get("markets", [])
            if not markets:
                break
            page_count += 1
            for market in markets:
                event_key = str(market.get("event_ticker")) if market.get("event_ticker") else None
                series_key = event_to_series.get(event_key or "")
                category = series_categories.get(series_key or "") or event_to_category.get(event_key or "") or "uncategorized"
                ticker = market.get("ticker")
                if not ticker:
                    continue
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

        return records, {"pages": page_count}

    async def sync_recent_direct_market_registry(
        self,
        *,
        event_to_series: dict[str, str],
        event_to_category: dict[str, str],
        series_categories: dict[str, str],
    ) -> tuple[list[MarketRecord], dict]:
        end_at = utc_now()
        start_at = end_at - timedelta(days=90)
        max_pages = self.settings.kalshi_direct_market_recent_max_pages
        records_by_ticker: dict[str, MarketRecord] = {}
        stats = {
            "statuses": {},
            "marketsScanned": 0,
            "volumePositiveMarkets": 0,
            "pages": 0,
            "partial": False,
        }

        query_specs: list[tuple[str, dict[str, str | int]]] = [
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

        return records, {
            "pages": page_count,
            "marketsScanned": markets_scanned,
            "volumePositiveMarkets": volume_positive,
            "records": len(records),
            "partial": bool(cursor),
        }

    async def fetch_event_maps(self, scope: str, series_categories: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        cursor: str | None = None
        event_to_series: dict[str, str] = {}
        event_to_category: dict[str, str] = {}
        max_pages = (
            self.settings.kalshi_event_bootstrap_max_pages
            if scope == "all"
            else self.settings.kalshi_event_recent_max_pages
        )
        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json("/events", params=params)
            events = payload.get("events", [])
            if not events:
                break
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
        return event_to_series, event_to_category

    async def fetch_cutoff(self) -> dict:
        return await self.client.get_json("/historical/cutoff")

    async def sync_recent_candles(self, ticker_categories: dict[str, str]) -> tuple[list[DailyVolumeRecord], dict]:
        if not ticker_categories:
            end_day = utc_now().date().isoformat()
            return [], {
                "chunks": 0,
                "tickers": 0,
                "marketsReturned": 0,
                "candlesProcessed": 0,
                "startDay": end_day,
                "endDay": end_day,
                "periodIntervalMinutes": 1440,
                "partial": False,
            }

        end_day = utc_now().date()
        start_day = end_day - timedelta(days=89)
        start_at = datetime.combine(start_day, time.min, tzinfo=UTC)
        end_at = datetime.combine(end_day, time.max, tzinfo=UTC)
        tickers = sorted(ticker_categories)
        chunk_size = self.settings.kalshi_candlestick_chunk_size
        max_parallel = min(6, max(2, self.settings.fetch_concurrency * 2))
        semaphore = asyncio.Semaphore(max_parallel)
        aggregated: dict[tuple[str, str], float] = defaultdict(float)
        stats = {
            "chunks": 0,
            "requests": 0,
            "tickers": len(tickers),
            "marketsReturned": 0,
            "candlesProcessed": 0,
            "startDay": start_day.isoformat(),
            "endDay": end_day.isoformat(),
            "periodIntervalMinutes": 1440,
            "partial": False,
            "failedChunks": 0,
            "failedTickers": [],
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

        chunks = [tickers[index : index + chunk_size] for index in range(0, len(tickers), chunk_size)]
        stats["chunks"] = len(chunks)
        results = await asyncio.gather(*(fetch_chunk_resilient(chunk) for chunk in chunks))

        for markets in results:
            stats["marketsReturned"] += len(markets)
            for market in markets:
                ticker = str(market.get("market_ticker"))
                category = ticker_categories.get(ticker) or "uncategorized"
                for candle in market.get("candlesticks", []) or []:
                    turnover = float(kalshi_candlestick_turnover_usd(candle))
                    if turnover <= 0:
                        continue
                    stats["candlesProcessed"] += 1
                    day_key = day_from_timestamp(candle.get("end_period_ts"))
                    aggregated[(day_key, category)] += turnover

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

    async def sync_trades(self, scope: str, category_lookup: callable) -> tuple[list[TradeRecord], dict]:
        cutoff_payload = await self.fetch_cutoff()
        cutoff_dt = coerce_timestamp(cutoff_payload.get("trades_created_ts"))
        recent_cutoff = utc_now() - timedelta(days=90)
        if scope == "all":
            live_trades, live_stats = await self._fetch_trades_stream(
                path="/markets/trades",
                scope=scope,
                stop_before=None,
                max_pages=self.settings.kalshi_bootstrap_max_pages,
                category_lookup=category_lookup,
            )
            historical_trades: list[TradeRecord] = []
            historical_stats = {"pages": 0, "partial": False}
            historical_trades, historical_stats = await self._fetch_trades_stream(
                path="/historical/trades",
                scope=scope,
                stop_before=None,
                max_pages=self.settings.kalshi_bootstrap_max_pages,
                category_lookup=category_lookup,
            )
            return live_trades + historical_trades, {
                "livePages": live_stats["pages"],
                "historicalPages": historical_stats["pages"],
                "cutoff": cutoff_dt.isoformat(),
                "partial": bool(live_stats.get("partial"))
                or bool(historical_stats.get("partial"))
                or (
                    live_stats.get("pages", 0) >= self.settings.kalshi_bootstrap_max_pages
                    or historical_stats.get("pages", 0) >= self.settings.kalshi_bootstrap_max_pages
                ),
            }

        live_start = max(recent_cutoff, cutoff_dt)
        live_end = utc_now()
        live_trades, live_stats = await self._fetch_trades_windowed(
            path="/markets/trades",
            start_at=live_start,
            end_at=live_end,
            category_lookup=category_lookup,
        )

        historical_trades = []
        historical_stats = {"windows": 0, "pages": 0, "partial": False}
        if recent_cutoff < cutoff_dt:
            historical_trades, historical_stats = await self._fetch_trades_windowed(
                path="/historical/trades",
                start_at=recent_cutoff,
                end_at=cutoff_dt,
                category_lookup=category_lookup,
            )

        return live_trades + historical_trades, {
            "livePages": live_stats["pages"],
            "historicalPages": historical_stats["pages"],
            "liveWindows": live_stats.get("windows", 0),
            "historicalWindows": historical_stats.get("windows", 0),
            "cutoff": cutoff_dt.isoformat(),
            "partial": bool(live_stats.get("partial")) or bool(historical_stats.get("partial")),
        }

    async def _fetch_trades_stream(
        self,
        *,
        path: str,
        scope: str,
        stop_before,
        max_pages: int,
        category_lookup: callable,
    ) -> tuple[list[TradeRecord], dict]:
        cursor: str | None = None
        page_count = 0
        trades: list[TradeRecord] = []
        oldest_seen = None

        for _ in range(max_pages):
            params: dict[str, str | int] = {"limit": min(self.settings.kalshi_page_limit, 1000)}
            if cursor:
                params["cursor"] = cursor
            payload = await self.client.get_json(path, params=params)
            batch = payload.get("trades", [])
            if not batch:
                break
            page_count += 1
            for trade in batch:
                trade_time = coerce_timestamp(trade.get("created_time"))
                oldest_seen = trade_time if oldest_seen is None else min(oldest_seen, trade_time)
                ticker = str(trade.get("ticker"))
                category = category_lookup(ticker) or "uncategorized"
                trades.append(
                    TradeRecord(
                        platform="kalshi",
                        trade_key=stable_trade_key(
                            trade.get("trade_id"),
                            trade.get("ticker"),
                            trade.get("created_time"),
                        ),
                        market_key=ticker,
                        trade_ts=trade_time.isoformat(),
                        day_utc=day_from_timestamp(trade.get("created_time")),
                        normalized_category=category,
                        turnover_usd=float(kalshi_turnover_usd(trade)),
                        source=path.lstrip("/"),
                    )
                )
            if stop_before is not None and oldest_seen is not None and oldest_seen <= stop_before:
                break
            cursor = payload.get("cursor")
            if not cursor:
                break

        return trades, {
            "pages": page_count,
            "oldestTrade": None if oldest_seen is None else oldest_seen.isoformat(),
            "partial": page_count >= max_pages,
        }

    async def _fetch_trades_windowed(
        self,
        *,
        path: str,
        start_at,
        end_at,
        category_lookup: callable,
    ) -> tuple[list[TradeRecord], dict]:
        if start_at >= end_at:
            return [], {"windows": 0, "pages": 0, "partial": False}

        trades: list[TradeRecord] = []
        window_count = 0
        total_pages = 0
        partial = False
        cursor_limit = self.settings.kalshi_trade_window_max_pages
        window_size = timedelta(days=self.settings.kalshi_recent_trade_window_days)
        min_window = timedelta(hours=self.settings.kalshi_trade_min_window_hours)
        windows: deque[tuple] = deque()
        cursor_start = start_at
        while cursor_start < end_at:
            cursor_end = min(cursor_start + window_size, end_at)
            windows.append((cursor_start, cursor_end))
            cursor_start = cursor_end

        while windows:
            window_start, window_end = windows.popleft()
            if window_start >= window_end:
                continue

            window_count += 1
            cursor: str | None = None
            page_in_window = 0
            window_records: list[TradeRecord] = []

            while page_in_window < cursor_limit:
                params: dict[str, str | int] = {
                    "limit": min(self.settings.kalshi_page_limit, 1000),
                    "min_ts": int(window_start.timestamp()),
                    "max_ts": int(window_end.timestamp()),
                }
                if cursor:
                    params["cursor"] = cursor
                payload = await self.client.get_json(path, params=params)
                batch = payload.get("trades", [])
                if not batch:
                    break

                page_in_window += 1
                total_pages += 1
                for trade in batch:
                    trade_time = coerce_timestamp(trade.get("created_time"))
                    ticker = str(trade.get("ticker"))
                    category = category_lookup(ticker) or "uncategorized"
                    window_records.append(
                        TradeRecord(
                            platform="kalshi",
                            trade_key=stable_trade_key(
                                trade.get("trade_id"),
                                trade.get("ticker"),
                                trade.get("created_time"),
                            ),
                            market_key=ticker,
                            trade_ts=trade_time.isoformat(),
                            day_utc=day_from_timestamp(trade.get("created_time")),
                            normalized_category=category,
                            turnover_usd=float(kalshi_turnover_usd(trade)),
                            source=path.lstrip("/"),
                        )
                    )

                cursor = payload.get("cursor")
                if not cursor:
                    break

            if cursor:
                span = window_end - window_start
                if span > min_window:
                    midpoint = window_start + (span / 2)
                    overlap = timedelta(seconds=1)
                    windows.appendleft((midpoint - overlap, window_end))
                    windows.appendleft((window_start, midpoint + overlap))
                    continue
                partial = True

            trades.extend(window_records)

        return trades, {
            "windows": window_count,
            "pages": total_pages,
            "partial": partial,
        }
