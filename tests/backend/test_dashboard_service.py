from pathlib import Path

from app.db.database import Database
from app.services.dashboard import DashboardService
from app.services.repository import Repository, TradeRecord


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
