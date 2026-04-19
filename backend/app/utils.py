from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


CATEGORY_ALIASES = {
    "us current affairs": "politics",
    "us-current-affairs": "politics",
    "politics": "politics",
    "elections": "politics",
    "finance": "finance",
    "financials": "finance",
    "crypto": "crypto",
    "sports": "sports",
    "weather": "weather",
    "tech": "tech",
    "technology": "tech",
    "economics": "economics",
    "economy": "economics",
    "culture": "entertainment",
    "entertainment": "entertainment",
    "world": "world",
    "mentions": "mentions",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def coerce_timestamp(value: str | int | float | None) -> datetime:
    if value is None:
        return utc_now()
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).astimezone(UTC)
        return datetime.fromisoformat(cleaned).astimezone(UTC)
    numeric = float(value)
    if numeric > 10_000_000_000:
        numeric /= 1000
    return datetime.fromtimestamp(numeric, tz=UTC)


def day_from_timestamp(value: str | int | float | None) -> str:
    return coerce_timestamp(value).date().isoformat()


def normalize_category(raw: str | None) -> str:
    if not raw or not raw.strip():
        return "uncategorized"
    lowered = raw.strip().replace("_", " ").replace("-", " ").lower()
    lowered = re.sub(r"\s+", " ", lowered)
    if lowered in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[lowered]
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-") or "uncategorized"


def display_category(slug: str) -> str:
    if slug == "uncategorized":
        return "Uncategorized"
    return " ".join(part.capitalize() for part in slug.split("-"))


def to_decimal(value: str | int | float | Decimal | None) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def polymarket_turnover_usd(trade: dict) -> Decimal:
    return quantize_money(to_decimal(trade.get("size")) * to_decimal(trade.get("price")))


def kalshi_turnover_usd(trade: dict) -> Decimal:
    price_key = "yes_price_dollars" if str(trade.get("taker_side", "")).lower() == "yes" else "no_price_dollars"
    return quantize_money(to_decimal(trade.get("count_fp")) * to_decimal(trade.get(price_key)))


def kalshi_candlestick_turnover_usd(candlestick: dict) -> Decimal:
    price = to_decimal((candlestick.get("price") or {}).get("mean_dollars"))
    return quantize_money(to_decimal(candlestick.get("volume_fp")) * price)


def stable_trade_key(*parts: object) -> str:
    joined = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def daterange(start_day: date, end_day: date) -> Iterable[date]:
    current = start_day
    while current <= end_day:
        yield current
        current += timedelta(days=1)
