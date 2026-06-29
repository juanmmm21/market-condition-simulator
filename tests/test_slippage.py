from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from market_condition_simulator.models import BookLiquidity, MarketConditionConfig, OrderSide
from market_condition_simulator.slippage import apply_slippage, calculate_slippage_bps


def _book() -> BookLiquidity:
    return BookLiquidity(
        symbol="BTCUSDT",
        best_bid=Decimal("99.9"),
        best_ask=Decimal("100.1"),
        bid_depth=Decimal("5"),
        ask_depth=Decimal("2"),
        event_time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


def test_buy_slippage_increases_execution_price() -> None:
    config = MarketConditionConfig()
    slippage = calculate_slippage_bps(OrderSide.BUY, Decimal("0.01"), _book(), config)
    execution = apply_slippage(Decimal("100"), OrderSide.BUY, slippage)
    assert execution > Decimal("100")


def test_sell_slippage_decreases_execution_price() -> None:
    config = MarketConditionConfig()
    slippage = calculate_slippage_bps(OrderSide.SELL, Decimal("0.01"), _book(), config)
    execution = apply_slippage(Decimal("100"), OrderSide.SELL, slippage)
    assert execution < Decimal("100")
