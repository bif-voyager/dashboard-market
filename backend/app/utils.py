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
    "social": "entertainment",
    "mentions": "entertainment",
    "entertainment": "entertainment",
    "world": "world",
    "geopolitics": "world",
    "unknown": "uncategorized",
    "other": "uncategorized",
    "exotics": "uncategorized",
    "science and technology": "science-and-technology",
    "climate and weather": "climate-and-weather",
    "education": "science-and-technology",
    "health": "science-and-technology",
    "transportation": "science-and-technology",
}

POLYMARKET_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "sports",
        (
            "nba",
            "nfl",
            "mlb",
            "nhl",
            "stanley cup",
            "world series",
            "super bowl",
            "champions league",
            "premier league",
            "finals",
            "playoffs",
            "tournament",
            "grand prix",
            "match",
            "goal",
            "touchdown",
            "tennis",
            "soccer",
            "baseball",
            "basketball",
            "football",
            "hurricanes win",
            "oilers win",
            "knicks win",
        ),
    ),
    (
        "crypto",
        (
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "solana",
            "xrp",
            "dogecoin",
            "crypto",
            "memecoin",
            "token",
            "airdrop",
        ),
    ),
    (
        "politics",
        (
            "trump",
            "election",
            "president",
            "senate",
            "house of representatives",
            "congress",
            "governor",
            "mayor",
            "white house",
            "democrat",
            "republican",
            "cabinet",
            "prime minister",
            "parliament",
            "impeach",
        ),
    ),
    (
        "world",
        (
            "russia",
            "ukraine",
            "ceasefire",
            "china",
            "taiwan",
            "israel",
            "gaza",
            "iran",
            "nato",
            "war",
            "invasion",
            "world leader",
        ),
    ),
    (
        "economics",
        (
            "inflation",
            "cpi",
            "gdp",
            "recession",
            "unemployment",
            "rate cut",
            "interest rate",
            "fed",
            "fomc",
            "tariff",
            "yield",
            "treasury",
        ),
    ),
    (
        "companies",
        (
            "apple",
            "microsoft",
            "amazon",
            "google",
            "meta",
            "tesla",
            "nvidia",
            "netflix",
            "uber",
            "openai",
            "bytedance",
            "tiktok",
            "spacex",
        ),
    ),
    (
        "science-and-technology",
        (
            "ai",
            "gpt",
            "chatgpt",
            "model release",
            "launch",
            "space",
            "rocket",
            "starship",
            "technology",
            "scientist",
        ),
    ),
    (
        "entertainment",
        (
            "album",
            "movie",
            "box office",
            "oscar",
            "grammy",
            "emmy",
            "celebrity",
            "rihanna",
            "playboi carti",
            "drake",
            "taylor swift",
            "gta",
            "season finale",
            "tv show",
        ),
    ),
    (
        "health",
        (
            "covid",
            "pandemic",
            "vaccine",
            "fda",
            "measles",
            "bird flu",
            "flu",
            "virus",
        ),
    ),
    (
        "climate-and-weather",
        (
            "weather",
            "temperature",
            "hurricane",
            "storm",
            "rainfall",
            "snowfall",
            "heatwave",
            "climate",
        ),
    ),
]


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


def infer_polymarket_category(
    *,
    raw_category: str | None,
    title: str | None = None,
    slug: str | None = None,
    event_title: str | None = None,
    event_slug: str | None = None,
) -> str:
    normalized = normalize_category(raw_category)
    if normalized != "uncategorized":
        return normalized

    haystack = " ".join(
        part.strip().lower()
        for part in (title or "", slug or "", event_title or "", event_slug or "")
        if part and part.strip()
    )
    if not haystack:
        return "uncategorized"

    for category, keywords in POLYMARKET_CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return category
    return "uncategorized"


def display_category(slug: str) -> str:
    if slug == "all":
        return "All markets"
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
    return quantize_money(to_decimal(trade.get("size")))


def kalshi_turnover_usd(trade: dict) -> Decimal:
    return quantize_money(to_decimal(trade.get("count_fp")))


def kalshi_candlestick_turnover_usd(candlestick: dict) -> Decimal:
    volume = candlestick.get("volume_fp")
    if volume is None:
        volume = candlestick.get("volume")
    return quantize_money(to_decimal(volume))


def stable_trade_key(*parts: object) -> str:
    joined = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def daterange(start_day: date, end_day: date) -> Iterable[date]:
    current = start_day
    while current <= end_day:
        yield current
        current += timedelta(days=1)
