from __future__ import annotations

from datetime import timedelta
from collections import defaultdict

from app.clients.base import PublicApiClient, UpstreamError
from app.config import Settings
from app.services.repository import CategorySnapshotRecord, MarketRecord, PlatformDailyVolumeRecord, TradeRecord
from app.utils import (
    coerce_timestamp,
    day_from_timestamp,
    infer_polymarket_category,
    normalize_category,
    polymarket_turnover_usd,
    stable_trade_key,
    utc_now,
)


class PolymarketAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gamma_client = PublicApiClient(
            base_url=settings.poly_gamma_base_url,
            source="polymarket-gamma",
            timeout_seconds=settings.request_timeout_seconds,
        )
        self.data_client = PublicApiClient(
            base_url=settings.poly_data_base_url,
            source="polymarket-data",
            timeout_seconds=settings.request_timeout_seconds,
        )

    async def close(self) -> None:
        await self.gamma_client.close()
        await self.data_client.close()

    async def sync_markets(self, scope: str) -> tuple[list[MarketRecord], list[CategorySnapshotRecord], dict]:
        max_pages = (
            self.settings.poly_metadata_bootstrap_max_pages
            if scope == "all"
            else self.settings.poly_metadata_recent_max_pages
        )
        limit = min(self.settings.poly_page_limit, 500)
        records, snapshots, pagination = await self._fetch_markets_keyset(max_pages=max_pages, limit=limit)
        if not records:
            records, snapshots, pagination = await self._fetch_markets_offset(max_pages=max_pages, limit=limit)
        return records, snapshots, pagination

    async def sync_builder_daily_volume(self) -> tuple[list[PlatformDailyVolumeRecord], dict]:
        payload = await self.data_client.get_json(
            "/v1/builders/volume",
            params={"timePeriod": "DAY", "limit": 5000},
        )
        rows = payload.get("value", []) if isinstance(payload, dict) else payload
        by_day: defaultdict[str, float] = defaultdict(float)
        raw_rows = 0
        for row in rows:
            raw_rows += 1
            day_value = row.get("dt")
            if not day_value:
                continue
            by_day[str(day_value)[:10]] += float(row.get("volume") or 0)

        records = [
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc=day,
                turnover_usd=round(volume, 2),
                source="builder-volume",
            )
            for day, volume in sorted(by_day.items())
        ]
        return records, {
            "source": "builder-volume",
            "rawRows": raw_rows,
            "days": len(records),
            "minDay": records[0].day_utc if records else None,
            "maxDay": records[-1].day_utc if records else None,
            "partial": not records,
        }

    async def _fetch_markets_keyset(
        self,
        *,
        max_pages: int,
        limit: int,
    ) -> tuple[list[MarketRecord], list[CategorySnapshotRecord], dict]:
        records: list[MarketRecord] = []
        category_snapshot = defaultdict(
            lambda: {"volume_24h": 0.0, "volume_1wk": 0.0, "volume_1mo": 0.0, "volume_total": 0.0}
        )
        first_market_id: str | None = None
        stalled = False
        cursor: str | None = None
        page_count = 0

        for page in range(max_pages):
            params: dict[str, str | int] = {"limit": limit}
            if cursor:
                params["after_cursor"] = cursor
            payload = await self.gamma_client.get_json("/markets/keyset", params=params)
            markets = payload.get("markets", [])
            if not markets:
                break
            page_count += 1
            if page == 0:
                first_market_id = str(markets[0].get("id"))
            elif first_market_id is not None and str(markets[0].get("id")) == first_market_id:
                stalled = True
                records.clear()
                break
            for market in markets:
                events = market.get("events") or []
                primary_event = events[0] if events else {}
                category = infer_polymarket_category(
                    raw_category=market.get("category"),
                    title=market.get("question"),
                    slug=market.get("slug"),
                    event_title=primary_event.get("title"),
                    event_slug=primary_event.get("slug"),
                )
                if market.get("conditionId"):
                    records.append(
                        MarketRecord(
                            platform="polymarket",
                            market_key=str(market.get("conditionId")),
                            title=market.get("question"),
                            raw_category=market.get("category"),
                            normalized_category=category,
                            source="gamma-keyset",
                        )
                    )
                category_snapshot[category]["volume_24h"] += float(market.get("volume24hr") or 0)
                category_snapshot[category]["volume_1wk"] += float(market.get("volume1wk") or 0)
                category_snapshot[category]["volume_1mo"] += float(market.get("volume1mo") or 0)
                category_snapshot[category]["volume_total"] += float(market.get("volume") or 0)

            cursor = payload.get("next_cursor")
            if not cursor:
                break

        return (
            records,
            [
                CategorySnapshotRecord(
                    platform="polymarket",
                    normalized_category=category,
                    volume_24h=values["volume_24h"],
                    volume_1wk=values["volume_1wk"],
                    volume_1mo=values["volume_1mo"],
                    volume_total=values["volume_total"],
                )
                for category, values in category_snapshot.items()
            ],
            {"mode": "keyset", "pages": page_count, "stalled": stalled},
        )

    async def _fetch_markets_offset(
        self,
        *,
        max_pages: int,
        limit: int,
    ) -> tuple[list[MarketRecord], list[CategorySnapshotRecord], dict]:
        records: list[MarketRecord] = []
        category_snapshot = defaultdict(
            lambda: {"volume_24h": 0.0, "volume_1wk": 0.0, "volume_1mo": 0.0, "volume_total": 0.0}
        )
        for page in range(max_pages):
            payload = await self.gamma_client.get_json(
                "/markets",
                params={"limit": limit, "offset": page * limit},
            )
            if not payload:
                break
            for market in payload:
                events = market.get("events") or []
                primary_event = events[0] if events else {}
                category = infer_polymarket_category(
                    raw_category=market.get("category"),
                    title=market.get("question"),
                    slug=market.get("slug"),
                    event_title=primary_event.get("title"),
                    event_slug=primary_event.get("slug"),
                )
                if market.get("conditionId"):
                    records.append(
                        MarketRecord(
                            platform="polymarket",
                            market_key=str(market.get("conditionId")),
                            title=market.get("question"),
                            raw_category=market.get("category"),
                            normalized_category=category,
                            source="gamma-offset",
                        )
                    )
                category_snapshot[category]["volume_24h"] += float(market.get("volume24hr") or 0)
                category_snapshot[category]["volume_1wk"] += float(market.get("volume1wk") or 0)
                category_snapshot[category]["volume_1mo"] += float(market.get("volume1mo") or 0)
                category_snapshot[category]["volume_total"] += float(market.get("volume") or 0)
            if len(payload) < limit:
                break
        return (
            records,
            [
                CategorySnapshotRecord(
                    platform="polymarket",
                    normalized_category=category,
                    volume_24h=values["volume_24h"],
                    volume_1wk=values["volume_1wk"],
                    volume_1mo=values["volume_1mo"],
                    volume_total=values["volume_total"],
                )
                for category, values in category_snapshot.items()
            ],
            {"mode": "offset", "pages": max_pages},
        )

    async def sync_trades(self, scope: str, category_lookup: callable) -> tuple[list[TradeRecord], dict]:
        limit = min(self.settings.poly_page_limit, 1000)
        max_pages = self.settings.poly_bootstrap_max_pages if scope == "all" else self.settings.poly_recent_max_pages
        cutoff = utc_now() - timedelta(days=90)
        trades: list[TradeRecord] = []
        pages_processed = 0
        oldest_seen = None
        offset_ceiling_hit = False

        for page in range(max_pages):
            try:
                payload = await self.data_client.get_json(
                    "/trades",
                    params={"limit": limit, "offset": page * limit},
                )
            except UpstreamError as exc:
                if exc.status_code == 400 and page > 0:
                    offset_ceiling_hit = True
                    break
                raise
            batch = payload if isinstance(payload, list) else payload.get("value", [])
            if not batch:
                break
            pages_processed += 1
            for trade in batch:
                trade_time = coerce_timestamp(trade.get("timestamp"))
                oldest_seen = trade_time if oldest_seen is None else min(oldest_seen, trade_time)
                category = category_lookup(str(trade.get("conditionId"))) or "uncategorized"
                turnover = polymarket_turnover_usd(trade)
                trades.append(
                    TradeRecord(
                        platform="polymarket",
                        trade_key=stable_trade_key(
                            trade.get("transactionHash"),
                            trade.get("conditionId"),
                            trade.get("timestamp"),
                            trade.get("side"),
                            trade.get("size"),
                            trade.get("price"),
                            trade.get("asset"),
                        ),
                        market_key=str(trade.get("conditionId")),
                        trade_ts=trade_time.isoformat(),
                        day_utc=day_from_timestamp(trade.get("timestamp")),
                        normalized_category=category,
                        turnover_usd=float(turnover),
                        source="data-trades",
                    )
                )
            if scope != "all" and oldest_seen is not None and oldest_seen <= cutoff:
                break
            if len(batch) < limit:
                break

        covered_recent_window = oldest_seen is not None and oldest_seen <= cutoff
        return trades, {
            "pages": pages_processed,
            "oldestTrade": None if oldest_seen is None else oldest_seen.isoformat(),
            "offsetCeilingHit": offset_ceiling_hit,
            "partial": (scope == "all" and (pages_processed >= max_pages or offset_ceiling_hit))
            or (scope != "all" and not covered_recent_window),
        }
