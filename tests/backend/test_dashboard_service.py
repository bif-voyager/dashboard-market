from pathlib import Path

from app.db.database import Database
from app.services.dashboard import DashboardService
from app.services.repository import CategorySnapshotRecord, PlatformDailyVolumeRecord, Repository, TradeRecord


def test_all_time_response_zero_fills_missing_days(tmp_path: Path) -> None:
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
    assert payload["points"][1]["polymarket"] == 0
    assert payload["points"][1]["kalshi"] == 0
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
    assert any("proportional estimate" in warning for warning in payload["warnings"])


def test_polymarket_platform_daily_series_is_used_for_full_category_selection(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "dashboard.db"))
    repository = Repository(database)
    service = DashboardService(repository)

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
    repository.replace_platform_daily_volumes(
        platform="polymarket",
        source="builder-volume",
        start_day="2026-04-13",
        end_day="2026-04-19",
        records=[
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-04-13",
                turnover_usd=12.0,
                source="builder-volume",
            ),
            PlatformDailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-04-19",
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
