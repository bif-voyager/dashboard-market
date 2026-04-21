from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from app.config import Settings
from app.models.api import PlatformDataQuality, VolumeResponse, VolumeTotals
from app.services.repository import Repository
from app.utils import daterange, display_category


class DashboardService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository

    def list_categories(self) -> list[dict]:
        return [
            {
                "slug": item["slug"],
                "label": display_category(item["slug"]),
                "platforms": item["platforms"],
            }
            for item in self.repository.list_categories()
        ]

    def build_volume_response(
        self,
        *,
        range_value: str,
        categories: list[str] | None,
        category_scope: str = "both",
    ) -> dict:
        selected_categories = [] if categories == [] else categories
        sync_states = self.repository.get_sync_states()
        warnings = self._build_sync_warnings(sync_states)
        stale = any(state["status"] == "error" for state in sync_states)
        partial = any(state["partial"] for state in sync_states)

        if selected_categories == []:
            return VolumeResponse(
                range=range_value,
                categories=[],
                timezone="UTC",
                asOf=self.repository.get_stats().get("latestDay"),
                partial=partial,
                stale=stale,
                warnings=warnings,
                dataQuality=self._build_data_quality(),
                categoryScope=category_scope,
                totals=VolumeTotals(polymarket=0, kalshi=0, difference=0, total=0),
                points=[],
            ).model_dump()

        platform_categories = self._query_categories_by_platform(selected_categories, category_scope)
        start_day, end_day = self._resolve_range(range_value, platform_categories)
        points = [] if start_day is None or end_day is None else self._build_points(start_day, end_day, platform_categories)
        if range_value == "all" and points:
            self._mask_all_time_platform_gaps(points, "polymarket", platform_categories["polymarket"])
            self._mask_all_time_platform_gaps(points, "kalshi", platform_categories["kalshi"])

        polymarket_total = round(sum(self._series_value(point["polymarket"]) for point in points), 2)
        kalshi_total = round(sum(self._series_value(point["kalshi"]) for point in points), 2)
        latest_day = points[-1]["date"] if points else self.repository.get_stats().get("latestDay")

        if not points:
            partial = True
            self._append_warning(
                warnings,
                "No Dune volume rows are cached yet. Add DUNE_API_KEY and run Refresh data to materialize the latest query results.",
            )
        if latest_day and self.repository.get_stats().get("latestDay") != latest_day:
            self._append_warning(
                warnings,
                "The current UTC day is excluded from the chart because daily volume can be incomplete until the day closes.",
            )
        if self._only_all_markets_category():
            self._append_warning(
                warnings,
                "Category filtering currently uses a single All markets category because the configured Dune queries return total daily volume only.",
            )
        if self._uses_kalshi_trade_report_fallback():
            self._append_warning(
                warnings,
                "Kalshi has one or more Dune category days corrected from kalshi.trade_report; those fallback rows are category-mapped from market metadata and should be treated as estimated.",
            )
        self._append_warning(
            warnings,
            "Daily volume is sourced from Dune latest saved-query results and cached in local SQLite.",
        )

        return VolumeResponse(
            range=range_value,
            categories=[] if selected_categories is None else selected_categories,
            categoryScope=category_scope,
            timezone="UTC",
            asOf=latest_day,
            partial=partial,
            stale=stale,
            warnings=warnings,
            dataQuality=self._build_data_quality(),
            totals=VolumeTotals(
                polymarket=polymarket_total,
                kalshi=kalshi_total,
                difference=round(polymarket_total - kalshi_total, 2),
                total=round(polymarket_total + kalshi_total, 2),
            ),
            points=points,
        ).model_dump()

    def _resolve_range(
        self,
        range_value: str,
        platform_categories: dict[str, list[str] | None],
    ) -> tuple[date | None, date | None]:
        min_days: list[str] = []
        max_days: list[str] = []
        for platform, categories in platform_categories.items():
            min_day, max_day = self.repository.get_platform_date_bounds(platform, categories)
            if min_day is not None and max_day is not None:
                min_days.append(min_day)
                max_days.append(max_day)

        if not min_days or not max_days:
            return None, None

        min_day = min(min_days)
        max_day = max(max_days)
        end_day = min(date.fromisoformat(max_day), self._latest_closed_day())
        if date.fromisoformat(min_day) > end_day:
            return None, None
        if range_value == "all":
            return date.fromisoformat(min_day), end_day

        day_count = {"7d": 7, "30d": 30, "90d": 90}[range_value]
        return end_day - timedelta(days=day_count - 1), end_day

    def _latest_closed_day(self) -> date:
        return datetime.now(UTC).date() - timedelta(days=1)

    def _query_categories(self, selected_categories: list[str] | None) -> list[str] | None:
        if selected_categories is None or "all" in selected_categories:
            return None
        return selected_categories

    def _query_categories_by_platform(
        self,
        selected_categories: list[str] | None,
        category_scope: str,
    ) -> dict[str, list[str] | None]:
        selected = self._query_categories(selected_categories)
        return {
            "polymarket": selected if category_scope in {"both", "polymarket"} else None,
            "kalshi": selected if category_scope in {"both", "kalshi"} else None,
        }

    def _build_points(
        self,
        start_day: date,
        end_day: date,
        platform_categories: dict[str, list[str] | None],
    ) -> list[dict]:
        bucketed: dict[str, dict[str, float]] = defaultdict(lambda: {"polymarket": 0.0, "kalshi": 0.0})
        platform_days = self.repository.get_platform_days(start_day.isoformat(), end_day.isoformat())
        for platform, categories in platform_categories.items():
            rows = self.repository.get_volume_rows(
                start_day.isoformat(),
                end_day.isoformat(),
                categories,
                platform=platform,
            )
            for row in rows:
                bucketed[row["day_utc"]][row["platform"]] += float(row["turnover_usd"])

        points: list[dict] = []
        for current_day in daterange(start_day, end_day):
            day_key = current_day.isoformat()
            polymarket_value = self._point_platform_value(bucketed, platform_days, day_key, "polymarket")
            kalshi_value = self._point_platform_value(bucketed, platform_days, day_key, "kalshi")
            points.append(
                {
                    "date": day_key,
                    "polymarket": polymarket_value,
                    "kalshi": kalshi_value,
                    "total": round(self._series_value(polymarket_value) + self._series_value(kalshi_value), 2),
                }
            )
        return points

    def _point_platform_value(
        self,
        bucketed: dict[str, dict[str, float]],
        platform_days: dict[str, set[str]],
        day_key: str,
        platform: str,
    ) -> float | None:
        if day_key not in platform_days.get(platform, set()):
            return None
        return round(bucketed[day_key][platform], 2)

    def _build_data_quality(self) -> dict[str, PlatformDataQuality]:
        kalshi_uses_fallback = self._uses_kalshi_trade_report_fallback()
        return {
            "polymarket": PlatformDataQuality(
                dailySeries="Dune saved query latest result cached as UTC daily rows",
                sourceType="derived",
                sourceLabel=f"Dune query {self.settings.dune_polymarket_query_id} latest result",
                categoryFilter=self._category_filter_label(),
                exact=False,
                isEstimated=False,
                partial=False,
                coverage="full",
                coverageReason="The local cache contains the full latest result returned by the configured Dune saved query. The Polymarket saved query currently starts at 2024-01-01 and uses SUM(amount) for CLOB trade rows.",
            ),
            "kalshi": PlatformDataQuality(
                dailySeries="Dune saved query latest result cached as UTC daily rows",
                sourceType="estimated" if kalshi_uses_fallback else "derived",
                sourceLabel=self._kalshi_source_label(kalshi_uses_fallback),
                categoryFilter=self._category_filter_label(),
                exact=False,
                isEstimated=kalshi_uses_fallback,
                partial=kalshi_uses_fallback,
                coverage="partial" if kalshi_uses_fallback else "full",
                coverageReason=(
                    "Most Kalshi rows come from the configured Dune category query; configured upstream gap or duplicate days are corrected from kalshi.trade_report with category metadata."
                    if kalshi_uses_fallback
                    else "The local cache contains the full latest result returned by the configured Dune saved query; freshness depends on Dune's dataset refresh cadence."
                ),
                rawTrades=(
                    "Used only for configured Kalshi category-query correction days."
                    if kalshi_uses_fallback
                    else None
                ),
            ),
        }

    def _kalshi_source_label(self, uses_fallback: bool) -> str:
        label = f"Dune query {self.settings.dune_kalshi_query_id} latest result"
        if uses_fallback:
            return f"{label} + kalshi.trade_report fallback"
        return label

    def _uses_kalshi_trade_report_fallback(self) -> bool:
        sources = self.repository.get_platform_sources().get("kalshi", {}).get("sources", [])
        return "dune-sql-kalshi-trade-report-fallback" in sources

    def _category_filter_label(self) -> str:
        if self._only_all_markets_category():
            return "total-only All markets category"
        return "Dune query category column aggregation"

    def _only_all_markets_category(self) -> bool:
        categories = self.repository.list_categories()
        return len(categories) == 1 and categories[0]["slug"] == "all"

    def _build_sync_warnings(self, sync_states: list[dict]) -> list[str]:
        warnings: list[str] = []
        for state in sync_states:
            if state["status"] == "error" and state["message"]:
                self._append_warning(warnings, state["message"])
            if state["status"] == "interrupted":
                self._append_warning(warnings, "Previous Dune sync was interrupted before completion.")
        return warnings

    def _mask_all_time_platform_gaps(
        self,
        points: list[dict],
        platform: str,
        categories: list[str] | None,
    ) -> None:
        min_day, max_day = self.repository.get_platform_date_bounds(platform, categories)
        for point in points:
            if min_day is None or max_day is None or point["date"] < min_day or point["date"] > max_day:
                point[platform] = None
                point["total"] = round(
                    self._series_value(point.get("polymarket")) + self._series_value(point.get("kalshi")),
                    2,
                )

    def _series_value(self, value: float | None) -> float:
        return 0.0 if value is None else float(value)

    def _append_warning(self, warnings: list[str], message: str) -> None:
        if message not in warnings:
            warnings.append(message)
