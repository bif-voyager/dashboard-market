from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.database import Database
from app.services.dashboard import DashboardService
from app.services.repository import (
    CategorySnapshotRecord,
    DailyVolumeRecord,
    MarketRecord,
    PlatformDailyVolumeRecord,
    Repository,
    TradeRecord,
)


def test_all_time_response_masks_leading_and_trailing_platform_gaps(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    repository.record_trades(
        [
            TradeRecord(
                platform="polymarket",
                trade_key="trade-1",
                market_key="market-1",
                trade_ts="2026-01-01T12:00:00+00:00",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=10.0,
                source="test",
            ),
            TradeRecord(
                platform="kalshi",
                trade_key="trade-2",
                market_key="market-2",
                trade_ts="2026-01-03T12:00:00+00:00",
                day_utc="2026-01-03",
                normalized_category="politics",
                turnover_usd=7.5,
                source="test",
            ),
        ]
    )

    payload = service.build_volume_response(range_value="all", categories=["politics"])

    assert [point["date"] for point in payload["points"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert payload["points"][0]["kalshi"] is None
    assert payload["points"][1]["polymarket"] is None
    assert payload["points"][1]["kalshi"] is None
    assert payload["points"][2]["polymarket"] is None
    assert payload["totals"]["polymarket"] == 10.0
    assert payload["totals"]["kalshi"] == 7.5


def test_polymarket_category_filter_scales_platform_daily_series(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    repository.upsert_category_snapshots(
        [
            CategorySnapshotRecord(
                platform="polymarket",
                normalized_category="sports",
                volume_24h=25.0,
                volume_1wk=100.0,
                volume_1mo=400.0,
                volume_total=1000.0,
            ),
            CategorySnapshotRecord(
                platform="polymarket",
                normalized_category="politics",
                volume_24h=75.0,
                volume_1wk=300.0,
                volume_1mo=1200.0,
                volume_total=3000.0,
            ),
        ]
    )
    repository.replace_platform_daily_volumes(
        platform="polymarket",
        source="builder-volume",
        start_day="2026-04-18",
        end_day="2026-04-19",
        records=[
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-04-18",
                turnover_usd=100.0,
                source="builder-volume",
            ),
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-04-19",
                turnover_usd=300.0,
                source="builder-volume",
            ),
        ]
    )
    repository.set_sync_state(
        platform="polymarket",
        scope="recent",
        status="completed",
        partial=True,
        stats={},
    )

    payload = service.build_volume_response(range_value="all", categories=["sports"])

    assert [point["polymarket"] for point in payload["points"]] == [25.0, 75.0]
    assert payload["totals"]["polymarket"] == 100.0
    assert any("estimated" in warning for warning in payload["warnings"])


def test_polymarket_platform_daily_series_is_used_for_full_category_selection(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    repository.upsert_markets(
        [
            MarketRecord(
                platform="polymarket",
                market_key="market-1",
                title="Sports market",
                raw_category="sports",
                normalized_category="sports",
                source="test",
            )
        ]
    )
    repository.upsert_category_snapshots(
        [
            CategorySnapshotRecord(
                platform="polymarket",
                normalized_category="sports",
                volume_24h=0.0,
                volume_1wk=0.0,
                volume_1mo=0.0,
                volume_total=0.0,
            )
        ]
    )
    end_day = datetime.now(UTC).date() - timedelta(days=1)
    start_day = end_day - timedelta(days=6)

    repository.replace_platform_daily_volumes(
        platform="polymarket",
        source="builder-volume",
        start_day=start_day.isoformat(),
        end_day=end_day.isoformat(),
        records=[
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc=start_day.isoformat(),
                turnover_usd=12.0,
                source="builder-volume",
            ),
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc=end_day.isoformat(),
                turnover_usd=30.0,
                source="builder-volume",
            ),
        ],
    )
    repository.set_sync_state(
        platform="polymarket",
        scope="recent",
        status="completed",
        partial=True,
        stats={},
    )

    payload = service.build_volume_response(range_value="7d", categories=["sports"])

    assert payload["points"][0]["polymarket"] == 12.0
    assert payload["points"][-1]["polymarket"] == 30.0
    assert payload["points"][1]["polymarket"] is None
    assert payload["totals"]["polymarket"] == 42.0
    assert any("builder-volume daily series" in warning for warning in payload["warnings"])


def test_fixed_ranges_exclude_current_incomplete_utc_day(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    repository.record_trades(
        [
            TradeRecord(
                platform="kalshi",
                trade_key="closed-day",
                market_key="market-1",
                trade_ts=f"{yesterday.isoformat()}T12:00:00+00:00",
                day_utc=yesterday.isoformat(),
                normalized_category="politics",
                turnover_usd=10.0,
                source="test",
            ),
            TradeRecord(
                platform="kalshi",
                trade_key="current-day",
                market_key="market-1",
                trade_ts=f"{today.isoformat()}T12:00:00+00:00",
                day_utc=today.isoformat(),
                normalized_category="politics",
                turnover_usd=99.0,
                source="test",
            ),
        ]
    )

    payload = service.build_volume_response(range_value="7d", categories=["politics"])

    assert payload["points"][-1]["date"] == yesterday.isoformat()
    assert payload["asOf"] == yesterday.isoformat()
    assert payload["totals"]["kalshi"] == 10.0
    assert any("current UTC day is excluded" in warning for warning in payload["warnings"])


def test_category_list_ignores_snapshot_only_categories(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    repository.upsert_category_snapshots(
        [
            CategorySnapshotRecord(
                platform="polymarket",
                normalized_category="snapshot-only",
                volume_24h=5.0,
                volume_1wk=5.0,
                volume_1mo=5.0,
                volume_total=5.0,
            )
        ]
    )
    repository.upsert_markets(
        [
            MarketRecord(
                platform="kalshi",
                market_key="market-1",
                title="Politics market",
                raw_category="politics",
                normalized_category="politics",
                source="test",
            )
        ]
    )

    categories = service.list_categories()

    assert [item["slug"] for item in categories] == ["politics"]


def test_kalshi_all_time_quality_uses_all_backfill_metadata(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

    repository.replace_daily_volumes(
        platform="kalshi",
        start_day="2026-01-01",
        end_day="2026-01-02",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=10.0,
            )
        ],
    )
    repository.set_sync_state(
        platform="kalshi",
        scope="recent",
        status="completed",
        partial=False,
        stats={},
    )
    repository.set_sync_state(
        platform="kalshi",
        scope="all",
        status="completed",
        partial=False,
        stats={"candleStats": {"startDay": "2026-01-01", "endDay": "2026-01-02"}},
    )

    payload = service.build_volume_response(range_value="all", categories=["politics"])

    assert payload["dataQuality"]["kalshi"]["coverage"] == "unknown"
    assert "capped raw public trade backfill" in payload["dataQuality"]["kalshi"]["sourceLabel"]
