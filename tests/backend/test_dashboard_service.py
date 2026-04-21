from pathlib import Path
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db.database import Database
from app.services.dashboard import DashboardService
from app.services.repository import DailyVolumeRecord, Repository


def build_service(tmp_path: Path) -> tuple[Repository, DashboardService]:
    settings = Settings(sqlite_path=str(tmp_path / "dashboard.db"))
    database = Database(settings.sqlite_path)
    repository = Repository(database)
    return repository, DashboardService(settings, repository)


def test_categories_expose_all_markets_before_first_sync(tmp_path: Path) -> None:
    _, service = build_service(tmp_path)

    categories = service.list_categories()

    assert categories == [
        {
            "slug": "all",
            "label": "All markets",
            "platforms": ["polymarket", "kalshi"],
        }
    ]


def test_fixed_range_is_cut_from_latest_cached_dune_day(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="all",
                turnover_usd=10.0,
                source_query_id=7345278,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-10",
                normalized_category="all",
                turnover_usd=20.0,
                source_query_id=7345278,
            ),
        ],
    )
    repository.replace_daily_volumes(
        platform="kalshi",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-01-09",
                normalized_category="all",
                turnover_usd=7.5,
                source_query_id=7345291,
            )
        ],
    )

    payload = service.build_volume_response(range_value="7d", categories=["all"])

    assert payload["points"][0]["date"] == "2026-01-04"
    assert payload["points"][-1]["date"] == "2026-01-10"
    assert payload["totals"]["polymarket"] == 20.0
    assert payload["totals"]["kalshi"] == 7.5


def test_current_utc_day_is_excluded_from_displayed_range(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc=yesterday.isoformat(),
                normalized_category="all",
                turnover_usd=10.0,
                source_query_id=7345278,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc=today.isoformat(),
                normalized_category="all",
                turnover_usd=99.0,
                source_query_id=7345278,
            ),
        ],
    )

    payload = service.build_volume_response(range_value="7d", categories=["all"])

    assert payload["points"][-1]["date"] == yesterday.isoformat()
    assert payload["totals"]["polymarket"] == 10.0
    assert any("current UTC day is excluded" in warning for warning in payload["warnings"])


def test_missing_platform_day_is_rendered_as_gap_not_zero(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-03-07",
                normalized_category="sports",
                turnover_usd=100.0,
                source_query_id=5997078,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-03-08",
                normalized_category="sports",
                turnover_usd=200.0,
                source_query_id=5997078,
            ),
        ],
    )
    repository.replace_daily_volumes(
        platform="kalshi",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-03-07",
                normalized_category="sports",
                turnover_usd=300.0,
                source_query_id=5906732,
            ),
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-03-09",
                normalized_category="sports",
                turnover_usd=400.0,
                source_query_id=5906732,
            ),
        ],
    )

    payload = service.build_volume_response(range_value="all", categories=["sports"])
    gap = next(point for point in payload["points"] if point["date"] == "2026-03-08")

    assert gap["polymarket"] == 200.0
    assert gap["kalshi"] is None
    assert gap["total"] == 200.0


def test_kalshi_trade_report_fallback_is_labeled_as_estimated(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="kalshi",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-03-08",
                normalized_category="sports",
                turnover_usd=190.0,
                source="dune-sql-kalshi-trade-report-fallback",
                source_query_id=0,
            )
        ],
    )

    payload = service.build_volume_response(range_value="all", categories=["sports"])

    assert payload["points"][0]["kalshi"] == 190.0
    assert payload["dataQuality"]["kalshi"]["isEstimated"] is True
    assert payload["dataQuality"]["kalshi"]["coverage"] == "partial"
    assert any("corrected from kalshi.trade_report" in warning for warning in payload["warnings"])


def test_all_time_response_masks_platform_gaps(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="all",
                turnover_usd=10.0,
                source_query_id=7345278,
            )
        ],
    )
    repository.replace_daily_volumes(
        platform="kalshi",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-01-03",
                normalized_category="all",
                turnover_usd=7.5,
                source_query_id=7345291,
            )
        ],
    )

    payload = service.build_volume_response(range_value="all", categories=["all"])

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


def test_empty_category_selection_returns_no_points(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="all",
                turnover_usd=10.0,
                source_query_id=7345278,
            )
        ],
    )

    payload = service.build_volume_response(range_value="30d", categories=[])

    assert payload["points"] == []
    assert payload["totals"]["total"] == 0


def test_non_all_categories_work_if_dune_query_returns_category_column(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="sports",
                turnover_usd=15.0,
                source_query_id=7345278,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=30.0,
                source_query_id=7345278,
            ),
        ],
    )

    payload = service.build_volume_response(range_value="all", categories=["sports"])

    assert payload["points"][0]["polymarket"] == 15.0
    assert payload["totals"]["polymarket"] == 15.0
    assert payload["dataQuality"]["polymarket"]["categoryFilter"] == "Dune query category column aggregation"


def test_category_list_omits_all_markets_when_real_categories_exist(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="sports",
                turnover_usd=15.0,
                source_query_id=7345278,
            )
        ],
    )

    assert [item["slug"] for item in service.list_categories()] == ["sports"]


def test_all_category_means_every_cached_category(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="sports",
                turnover_usd=15.0,
                source_query_id=7345278,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=30.0,
                source_query_id=7345278,
            ),
        ],
    )

    payload = service.build_volume_response(range_value="all", categories=["all"])

    assert payload["totals"]["polymarket"] == 45.0


def test_category_scope_can_filter_only_one_platform(tmp_path: Path) -> None:
    repository, service = build_service(tmp_path)
    repository.replace_daily_volumes(
        platform="polymarket",
        records=[
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="sports",
                turnover_usd=10.0,
                source_query_id=5997078,
            ),
            DailyVolumeRecord(
                platform="polymarket",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=30.0,
                source_query_id=5997078,
            ),
        ],
    )
    repository.replace_daily_volumes(
        platform="kalshi",
        records=[
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-01-01",
                normalized_category="sports",
                turnover_usd=100.0,
                source_query_id=7345291,
            ),
            DailyVolumeRecord(
                platform="kalshi",
                day_utc="2026-01-01",
                normalized_category="politics",
                turnover_usd=300.0,
                source_query_id=7345291,
            ),
        ],
    )

    payload = service.build_volume_response(
        range_value="all",
        categories=["sports"],
        category_scope="polymarket",
    )

    assert payload["categoryScope"] == "polymarket"
    assert payload["totals"]["polymarket"] == 10.0
    assert payload["totals"]["kalshi"] == 400.0
