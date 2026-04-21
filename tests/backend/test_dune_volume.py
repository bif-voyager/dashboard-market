from app.services.dune_volume import parse_day, parse_money, records_from_dune_rows


def test_parse_day_accepts_dune_utc_timestamp_string() -> None:
    assert parse_day("2026-04-19 00:00:00.000 UTC").isoformat() == "2026-04-19"


def test_parse_day_treats_naive_dune_timestamp_as_utc() -> None:
    assert parse_day("2026-04-19 00:00:00.000").isoformat() == "2026-04-19"


def test_parse_money_rounds_to_cents() -> None:
    assert str(parse_money("10.125")) == "10.13"


def test_records_from_dune_rows_defaults_to_all_category() -> None:
    records = records_from_dune_rows(
        platform="polymarket",
        query_id=7345278,
        rows=[{"day": "2026-04-19", "daily_volume_usd": "123.45"}],
    )

    assert records[0].day_utc == "2026-04-19"
    assert records[0].normalized_category == "all"
    assert records[0].turnover_usd == 123.45


def test_records_from_dune_rows_uses_category_when_present() -> None:
    records = records_from_dune_rows(
        platform="kalshi",
        query_id=7345291,
        rows=[{"date": "2026-04-19", "volume_usd": 9, "category": "Politics"}],
    )

    assert records[0].normalized_category == "politics"


def test_records_from_dune_rows_accepts_uppercase_volume_column() -> None:
    records = records_from_dune_rows(
        platform="kalshi",
        query_id=5906732,
        rows=[{"date": "2026-04-19", "Volume": 123.45, "category": "Financials"}],
    )

    assert records[0].normalized_category == "finance"
    assert records[0].turnover_usd == 123.45


def test_records_from_dune_rows_accepts_filarm_polymarket_volume_column() -> None:
    records = records_from_dune_rows(
        platform="polymarket",
        query_id=5997078,
        rows=[
            {
                "date": "2026-04-19 00:00:00.000 UTC",
                "category": "Economy",
                "taker_notional_volume": 12.34,
            }
        ],
    )

    assert records[0].day_utc == "2026-04-19"
    assert records[0].normalized_category == "economics"
    assert records[0].turnover_usd == 12.34


def test_records_from_dune_rows_preserves_custom_source() -> None:
    records = records_from_dune_rows(
        platform="kalshi",
        query_id=0,
        rows=[{"day": "2026-03-08", "daily_volume_usd": 100, "category": "Sports"}],
        source="dune-sql-kalshi-trade-report-fallback",
    )

    assert records[0].source == "dune-sql-kalshi-trade-report-fallback"
