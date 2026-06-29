from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from market_condition_simulator.models import (
    ExecutionOrder,
    MarketConditionConfig,
    MarketTick,
    OrderSide,
)
from market_condition_simulator.simulator import MarketConditionSimulator


def test_simulator_delays_execution_until_tick() -> None:
    config = MarketConditionConfig(latency_ms=50)
    simulator = MarketConditionSimulator(config)
    order = ExecutionOrder(
        order_id="ord-1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.01"),
        submitted_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    simulator.submit_order(order, book=None)
    assert simulator.pending_count == 1

    early_tick = MarketTick(
        symbol="BTCUSDT",
        price=Decimal("100"),
        event_time=datetime(2024, 1, 1, 12, 0, 0, 20_000, tzinfo=UTC),
    )
    assert simulator.process_tick(early_tick, book=None) == []

    late_tick = MarketTick(
        symbol="BTCUSDT",
        price=Decimal("100.5"),
        event_time=datetime(2024, 1, 1, 12, 0, 0, 100_000, tzinfo=UTC),
    )
    results = simulator.process_tick(late_tick, book=None)
    assert len(results) == 1
    assert results[0].execution_price > late_tick.price
    assert results[0].latency_ms >= 50
