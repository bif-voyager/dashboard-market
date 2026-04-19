from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from app.models.api import VolumeResponse, VolumeTotals
from app.services.repository import Repository
from app.utils import daterange, display_category


class DashboardService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_categories(self) -> list[dict]:
        categories = self.repository.list_categories()
        return [
            {
                "slug": item["slug"],
                "label": display_category(item["slug"]),
                "platforms": item["platforms"],
            }
            for item in categories
        ]

    def build_volume_response(self, *, range_value: str, categories: list[str] | None) -> dict:
        selected_categories = [] if categories == [] else categories
        sync_states = self.repository.get_sync_states()
        warnings = [state["message"] for state in sync_states if state["status"] == "error" and state["message"]]
        stale = bool(warnings)
        partial = any(state["partial"] for state in sync_states if state["scope"] in {"recent", "all"})

        if selected_categories == []:
            return VolumeResponse(
                range=range_value,
                categories=[],
                timezone="UTC",
                asOf=self.repository.get_stats().get("latestDay"),
                partial=partial,
                stale=stale,
                warnings=warnings,
                totals=VolumeTotals(polymarket=0, kalshi=0, difference=0, total=0),
                points=[],
            ).model_dump()

        end_day = datetime.now(UTC).date()
        if range_value == "all":
            min_day, max_day = self.repository.get_date_bounds(selected_categories)
            if min_day is None or max_day is None:
                points = []
            else:
                start_date = date.fromisoformat(min_day)
                end_day = date.fromisoformat(max_day)
                points = self._build_points(start_date, end_day, selected_categories)
        else:
            day_count = {"7d": 7, "30d": 30, "90d": 90}[range_value]
            start_date = end_day - timedelta(days=day_count - 1)
            points = self._build_points(start_date, end_day, selected_categories)

        polymarket_total = round(sum(point["polymarket"] for point in points), 2)
        kalshi_total = round(sum(point["kalshi"] for point in points), 2)
        latest_day = self.repository.get_stats().get("latestDay")
        poly_recent_state = next(
            (
                state
                for state in sync_states
                if state["platform"] == "polymarket" and state["scope"] == "recent"
            ),
            None,
        )
        if poly_recent_state and poly_recent_state["partial"]:
            warnings.append(
                "Polymarket daily trade history is partial because the public trades endpoint does not expose a full 90-day exchange-wide backfill."
            )
            snapshot_total = self.repository.get_snapshot_total(
                platform="polymarket",
                range_value=range_value,
                categories=selected_categories,
            )
            if snapshot_total is not None and snapshot_total > polymarket_total:
                polymarket_total = round(snapshot_total, 2)
                warnings.append(
                    "Polymarket total is supplemented from market metadata because public trade pagination is incomplete."
                )
        return VolumeResponse(
            range=range_value,
            categories=[] if selected_categories is None else selected_categories,
            timezone="UTC",
            asOf=latest_day,
            partial=partial,
            stale=stale,
            warnings=warnings,
            totals=VolumeTotals(
                polymarket=polymarket_total,
                kalshi=kalshi_total,
                difference=round(polymarket_total - kalshi_total, 2),
                total=round(polymarket_total + kalshi_total, 2),
            ),
            points=points,
        ).model_dump()

    def _build_points(self, start_date: date, end_date: date, categories: list[str] | None) -> list[dict]:
        rows = self.repository.get_volume_rows(start_date.isoformat(), end_date.isoformat(), categories)
        bucketed: dict[str, dict[str, float]] = defaultdict(lambda: {"polymarket": 0.0, "kalshi": 0.0})
        for row in rows:
            bucketed[row["day_utc"]][row["platform"]] += float(row["turnover_usd"])

        points: list[dict] = []
        for current_day in daterange(start_date, end_date):
            day_key = current_day.isoformat()
            polymarket_value = round(bucketed[day_key]["polymarket"], 2)
            kalshi_value = round(bucketed[day_key]["kalshi"], 2)
            points.append(
                {
                    "date": day_key,
                    "polymarket": polymarket_value,
                    "kalshi": kalshi_value,
                    "total": round(polymarket_value + kalshi_value, 2),
                }
            )
        return points
