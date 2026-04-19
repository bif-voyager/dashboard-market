from decimal import Decimal

from app.utils import infer_polymarket_category, kalshi_turnover_usd, normalize_category, polymarket_turnover_usd


def test_polymarket_turnover_uses_contract_notional() -> None:
    assert polymarket_turnover_usd({"size": 10, "price": 0.63}) == Decimal("10.00")


def test_kalshi_turnover_uses_contract_notional() -> None:
    assert kalshi_turnover_usd({"count_fp": "10.00", "yes_price_dollars": "0.5600"}) == Decimal("10.00")


def test_normalize_category_collapses_equivalent_labels() -> None:
    assert normalize_category("Politics") == "politics"
    assert normalize_category(" politics ") == "politics"
    assert normalize_category("US-current-affairs") == "politics"
    assert normalize_category("Financials") == "finance"


def test_infer_polymarket_category_uses_question_and_slug_keywords() -> None:
    assert (
        infer_polymarket_category(
            raw_category=None,
            title="Will the Edmonton Oilers win the 2026 NHL Stanley Cup?",
            slug="will-the-edmonton-oilers-win-the-2026-nhl-stanley-cup",
        )
        == "sports"
    )
    assert (
        infer_polymarket_category(
            raw_category=None,
            title="Will bitcoin hit $1m before GTA VI?",
            slug="will-bitcoin-hit-1m-before-gta-vi",
        )
        == "crypto"
    )
    assert (
        infer_polymarket_category(
            raw_category=None,
            title="Trump out as President before GTA VI?",
            slug="trump-out-as-president-before-gta-vi",
        )
        == "politics"
    )
