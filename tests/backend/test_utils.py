from decimal import Decimal

from app.utils import kalshi_turnover_usd, normalize_category, polymarket_turnover_usd


def test_polymarket_turnover_uses_size_times_price() -> None:
    assert polymarket_turnover_usd({"size": 10, "price": 0.63}) == Decimal("6.30")


def test_kalshi_turnover_uses_taker_side_specific_price() -> None:
    assert (
        kalshi_turnover_usd(
            {
                "count_fp": "10.00",
                "taker_side": "yes",
                "yes_price_dollars": "0.5600",
                "no_price_dollars": "0.4400",
            }
        )
        == Decimal("5.60")
    )
    assert (
        kalshi_turnover_usd(
            {
                "count_fp": "10.00",
                "taker_side": "no",
                "yes_price_dollars": "0.5600",
                "no_price_dollars": "0.4400",
            }
        )
        == Decimal("4.40")
    )


def test_normalize_category_collapses_equivalent_labels() -> None:
    assert normalize_category("Politics") == "politics"
    assert normalize_category(" politics ") == "politics"
    assert normalize_category("US-current-affairs") == "politics"
    assert normalize_category("Financials") == "finance"
