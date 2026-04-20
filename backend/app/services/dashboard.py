from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from app.models.api import PlatformDataQuality, VolumeResponse, VolumeTotals
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
        warnings: list[str] = []
        for state in sync_states:
            if state["status"] == "error" and state["message"]:
                self._append_warning(warnings, state["message"])
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

        polymarket_category_scale = self._polymarket_category_scale(
            range_value=range_value,
            categories=selected_categories,
        )
        end_day = self._latest_closed_day()
        if range_value == "all":
            min_day, max_day = self.repository.get_date_bounds(selected_categories)
            if polymarket_category_scale is not None and polymarket_category_scale > 0:
                poly_min_day, poly_max_day = self.repository.get_platform_date_bounds("polymarket")
                min_candidates = [value for value in (min_day, poly_min_day) if value is not None]
                max_candidates = [value for value in (max_day, poly_max_day) if value is not None]
                min_day = min(min_candidates) if min_candidates else None
                max_day = max(max_candidates) if max_candidates else None
            if min_day is None or max_day is None:
                points = []
            else:
                start_date = date.fromisoformat(min_day)
                end_day = min(date.fromisoformat(max_day), self._latest_closed_day())
                points = self._build_points(start_date, end_day, selected_categories)
        else:
            day_count = {"7d": 7, "30d": 30, "90d": 90}[range_value]
            start_date = end_day - timedelta(days=day_count - 1)
            points = self._build_points(start_date, end_day, selected_categories)

        polymarket_scaled_series_used = False
        if points and polymarket_category_scale is not None:
            polymarket_scaled_series_used = self._overlay_polymarket_platform_series(
                points,
                scale=polymarket_category_scale,
            )
        if range_value == "all" and points:
            self._mask_all_time_platform_gaps(
                points,
                platform="kalshi",
                min_day_max_day=self.repository.get_daily_platform_date_bounds("kalshi", selected_categories),
            )
            if not polymarket_scaled_series_used:
                self._mask_all_time_platform_gaps(
                    points,
                    platform="polymarket",
                    min_day_max_day=self.repository.get_daily_platform_date_bounds("polymarket", selected_categories),
                )

        polymarket_total = round(sum(self._series_value(point["polymarket"]) for point in points), 2)
        kalshi_total = round(sum(self._series_value(point["kalshi"]) for point in points), 2)
        latest_day = points[-1]["date"] if points else self.repository.get_stats().get("latestDay")
        if self.repository.get_stats().get("latestDay") != latest_day:
            self._append_warning(
                warnings,
                "The current UTC day is excluded from the chart because public daily endpoints can be incomplete until the day closes."
            )
        poly_recent_state = next(
            (
                state
                for state in sync_states
                if state["platform"] == "polymarket" and state["scope"] == "recent"
            ),
            None,
        )
        if poly_recent_state and poly_recent_state["partial"]:
            if polymarket_scaled_series_used:
                if selected_categories is None or polymarket_category_scale == 1:
                    self._append_warning(
                        warnings,
                        "Polymarket chart uses the public builder-volume daily series as a platform-level public proxy; raw trades are only sampled for diagnostics."
                    )
                else:
                    self._append_warning(
                        warnings,
                        "Polymarket category filters are estimated: public builder-volume daily series scaled by selected-category metadata share."
                    )
            else:
                self._append_warning(
                    warnings,
                    "Polymarket has no materialized daily data for the selected categories in this range."
                )
        kalshi_recent_state = next(
            (
                state
                for state in sync_states
                if state["platform"] == "kalshi" and state["scope"] == "recent"
            ),
            None,
        )
        kalshi_all_state = next(
            (
                state
                for state in sync_states
                if state["platform"] == "kalshi" and state["scope"] == "all"
            ),
            None,
        )
        if kalshi_recent_state:
            self._append_warning(
                warnings,
                "Kalshi daily series is derived from public candlestick volume over the materialized market registry."
            )
            if kalshi_recent_state["partial"]:
                self._append_warning(
                    warnings,
                    "Kalshi totals are materialized from the current registry subset; direct market pagination did not exhaust all open/settled markets."
                )
        data_quality = {
            "polymarket": self._build_polymarket_quality(
                selected_categories=selected_categories,
                polymarket_category_scale=polymarket_category_scale,
                polymarket_scaled_series_used=polymarket_scaled_series_used,
                poly_recent_state=poly_recent_state,
            ),
            "kalshi": self._build_kalshi_quality(
                range_value=range_value,
                kalshi_recent_state=kalshi_recent_state,
                kalshi_all_state=kalshi_all_state,
            ),
        }
        if not self._has_platform_warning(warnings, "Polymarket"):
            if data_quality["polymarket"].isEstimated:
                self._append_warning(
                    warnings,
                    "Polymarket category filters are estimated: public builder-volume daily series scaled by selected-category metadata share.",
                )
            elif data_quality["polymarket"].sourceType == "proxy":
                self._append_warning(
                    warnings,
                    "Polymarket chart uses the public builder-volume daily series as a platform-level public proxy; raw trades are only sampled for diagnostics.",
                )
            else:
                self._append_warning(
                    warnings,
                    "Polymarket daily rows are aggregated from sampled public trades and remain partial.",
                )
        if not self._has_platform_warning(warnings, "Kalshi"):
            self._append_warning(
                warnings,
                "Kalshi daily series is derived from public candlestick volume over the materialized market registry.",
            )
        return VolumeResponse(
            range=range_value,
            categories=[] if selected_categories is None else selected_categories,
            timezone="UTC",
            asOf=latest_day,
            partial=partial,
            stale=stale,
            warnings=warnings,
            dataQuality=data_quality,
            totals=VolumeTotals(
                polymarket=polymarket_total,
                kalshi=kalshi_total,
                difference=round(polymarket_total - kalshi_total, 2),
                total=round(polymarket_total + kalshi_total, 2),
            ),
            points=points,
        ).model_dump()

    def _build_polymarket_quality(
        self,
        *,
        selected_categories: list[str] | None,
        polymarket_category_scale: float | None,
        polymarket_scaled_series_used: bool,
        poly_recent_state: dict | None,
    ) -> PlatformDataQuality:
        if polymarket_scaled_series_used:
            if selected_categories is not None and polymarket_category_scale not in {None, 1}:
                return PlatformDataQuality(
                    dailySeries="public builder-volume platform proxy",
                    sourceType="estimated",
                    sourceLabel="Polymarket public builder-volume proxy scaled by category metadata share",
                    categoryFilter="proportional metadata-share estimate",
                    exact=False,
                    isEstimated=True,
                    partial=True,
                    coverage="partial",
                    coverageReason="Public builder analytics do not expose exact exchange-wide daily category history.",
                    rawTrades=(poly_recent_state or {}).get("stats", {}).get("tradeStats", {}).get("mode"),
                )
            return PlatformDataQuality(
                dailySeries="public builder-volume platform proxy",
                sourceType="proxy",
                sourceLabel="Polymarket public builder-volume platform proxy",
                categoryFilter="unfiltered platform proxy",
                exact=False,
                isEstimated=False,
                partial=True,
                coverage="partial",
                coverageReason="Public builder analytics are real data but not guaranteed exchange-wide canonical volume.",
                rawTrades=(poly_recent_state or {}).get("stats", {}).get("tradeStats", {}).get("mode"),
            )

        return PlatformDataQuality(
            dailySeries="sampled public trades aggregated by UTC day",
            sourceType="derived",
            sourceLabel="Polymarket sampled-trade aggregation from discovered event and market candidates",
            categoryFilter="materialized sampled-trade aggregation",
            exact=False,
            isEstimated=False,
            partial=True,
            coverage="partial",
            coverageReason="Raw trades are synced from capped event and market samples rather than a full exchange-wide backfill.",
            rawTrades=(poly_recent_state or {}).get("stats", {}).get("tradeStats", {}).get("mode"),
        )

    def _build_kalshi_quality(
        self,
        *,
        range_value: str,
        kalshi_recent_state: dict | None,
        kalshi_all_state: dict | None,
    ) -> PlatformDataQuality:
        partial = bool(kalshi_recent_state and kalshi_recent_state["partial"]) or bool(
            kalshi_all_state and kalshi_all_state["partial"]
        )
        if range_value == "all":
            if kalshi_all_state and kalshi_all_state["status"] == "completed":
                daily_series = "mixed materialized history: recent public candlesticks plus older capped raw-trade backfill"
                source_label = "Kalshi recent candlestick rows extended backward by capped raw public trade backfill"
                coverage = "partial" if partial else "unknown"
                coverage_reason = (
                    "Recent rows come from public market candlesticks; older rows are added from raw public trades over the Kalshi backfill window. "
                    "Heavy historical days are capped by page budget, so these older rows are not canonical full-day totals."
                )
            else:
                daily_series = "materialized history: recent candlestick-derived window plus older cached rows if available"
                source_label = "Kalshi materialized cache mixing recent candlestick rows with older cached history"
                coverage = "partial" if partial else "unknown"
                coverage_reason = (
                    "Recent rows come from public candlesticks; older rows only exist if they were previously materialized into the local cache."
                )
        else:
            daily_series = "public candlestick volume over materialized market registry"
            source_label = "Kalshi public candlestick-derived daily series"
            coverage = "partial" if partial else "unknown"
            coverage_reason = "Recent rows are aggregated from public market candlesticks over the discovered ticker universe."

        if partial:
            coverage_reason += " Coverage is partial because market discovery or candle fetches hit public API limits."

        return PlatformDataQuality(
            dailySeries=daily_series,
            sourceType="derived",
            sourceLabel=source_label,
            categoryFilter="registry category aggregation",
            exact=False,
            isEstimated=False,
            partial=partial,
            coverage=coverage,
            coverageReason=coverage_reason,
        )

    def _latest_closed_day(self) -> date:
        return datetime.now(UTC).date() - timedelta(days=1)

    def _should_use_polymarket_platform_series(self, categories: list[str] | None) -> bool:
        if categories is None:
            return True
        platform_categories = set(self.repository.list_platform_categories("polymarket"))
        return bool(platform_categories) and platform_categories.issubset(set(categories))

    def _polymarket_category_scale(self, *, range_value: str, categories: list[str] | None) -> float | None:
        if categories == []:
            return 0.0
        if self._should_use_polymarket_platform_series(categories):
            return 1.0

        snapshot_range = self._polymarket_snapshot_range_for_scale(range_value)
        if snapshot_range is None:
            return None
        selected_total = self.repository.get_snapshot_total(
            platform="polymarket",
            range_value=snapshot_range,
            categories=categories,
        )
        all_total = self.repository.get_snapshot_total(
            platform="polymarket",
            range_value=snapshot_range,
            categories=None,
        )
        if all_total is None or all_total <= 0 or selected_total is None:
            return None
        return max(0.0, min(float(selected_total) / float(all_total), 1.0))

    def _polymarket_snapshot_range_for_scale(self, range_value: str) -> str | None:
        if range_value == "7d":
            return "7d"
        if range_value in {"30d", "90d"}:
            return "30d"
        if range_value == "all":
            return "all"
        return None

    def _overlay_polymarket_platform_series(self, points: list[dict], *, scale: float) -> bool:
        rows = self.repository.get_platform_volume_rows(
            "polymarket",
            points[0]["date"],
            points[-1]["date"],
        )
        if not rows:
            return False

        if scale <= 0:
            for point in points:
                point["polymarket"] = 0.0
                point["total"] = round(point["kalshi"], 2)
            return True

        by_day = {row["day_utc"]: round(float(row["turnover_usd"]), 2) for row in rows}
        for point in points:
            raw_value = by_day.get(point["date"])
            polymarket_value = None if raw_value is None else round(raw_value * scale, 2)
            point["polymarket"] = polymarket_value
            point["total"] = round(self._series_value(polymarket_value) + point["kalshi"], 2)
        return True

    def _series_value(self, value: float | None) -> float:
        return 0.0 if value is None else float(value)

    def _mask_all_time_platform_gaps(
        self,
        points: list[dict],
        *,
        platform: str,
        min_day_max_day: tuple[str | None, str | None],
    ) -> None:
        min_day, max_day = min_day_max_day
        for point in points:
            if min_day is None or max_day is None or point["date"] < min_day or point["date"] > max_day:
                point[platform] = None
                point["total"] = round(
                    self._series_value(point.get("polymarket")) + self._series_value(point.get("kalshi")),
                    2,
                )

    def _append_warning(self, warnings: list[str], message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    def _has_platform_warning(self, warnings: list[str], platform_name: str) -> bool:
        return any(platform_name in warning for warning in warnings)

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
