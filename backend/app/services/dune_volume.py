from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.services.repository import DailyVolumeRecord
from app.utils import normalize_category


DAY_COLUMNS = ("day", "date", "trade_day", "block_day", "dt", "timestamp")
VOLUME_COLUMNS = (
    "daily_volume_usd",
    "volume_usd",
    "volume",
    "turnover_usd",
    "amount_usd",
    "notional_usd",
    "taker_notional_volume",
)
CATEGORY_COLUMNS = ("normalized_category", "category", "market_category")


def records_from_dune_rows(
    *,
    platform: str,
    query_id: int,
    rows: list[dict[str, Any]],
    source: str = "dune-query-latest-result",
) -> list[DailyVolumeRecord]:
    records: list[DailyVolumeRecord] = []
    for index, row in enumerate(rows):
        day_value = _first_present(row, DAY_COLUMNS)
        volume_value = _first_present(row, VOLUME_COLUMNS)
        if day_value is None:
            raise ValueError(f"Dune {platform} row #{index + 1} has no day/date column")
        if volume_value is None:
            raise ValueError(f"Dune {platform} row #{index + 1} has no USD volume column")

        category_value = _first_present(row, CATEGORY_COLUMNS)
        category = normalize_category(str(category_value)) if category_value not in {None, ""} else "all"
        records.append(
            DailyVolumeRecord(
                platform=platform,
                day_utc=parse_day(day_value).isoformat(),
                normalized_category=category,
                turnover_usd=float(parse_money(volume_value)),
                source=source,
                source_query_id=query_id,
            )
        )
    return records


def parse_day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, tz=UTC).date()
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Empty date value")
        if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
            return date.fromisoformat(cleaned)
        cleaned = cleaned.replace("Z", "+00:00")
        if cleaned.endswith(" UTC"):
            cleaned = f"{cleaned[:-4]}+00:00"
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).date()
    raise ValueError(f"Unsupported date value: {value!r}")


def parse_money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Unsupported volume value: {value!r}") from exc


def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    lower_to_original = {key.lower(): key for key in row}
    for name in names:
        key = lower_to_original.get(name)
        if key is not None and row.get(key) is not None:
            return row[key]
    return None
