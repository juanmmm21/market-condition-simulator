from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from market_condition_simulator.models import OrderSide
from market_condition_simulator.queue import (
    FillModel,
    LimitOrder,
    simulate_limit_orders,
)

T0 = datetime(2026, 11, 17, 23, 0, tzinfo=UTC)


def _t(ms: int) -> str:
    return (T0 + timedelta(milliseconds=ms)).isoformat()


def _snapshot(ms: int, bids: dict[str, str], asks: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "book_snapshot",
        "event_time": _t(ms),
        "bids": [[p, q] for p, q in bids.items()],
        "asks": [[p, q] for p, q in asks.items()],
    }


def _diff(ms: int, bids: dict[str, str], asks: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "type": "book_diff",
        "event_time": _t(ms),
        "bids": [[p, q] for p, q in bids.items()],
        "asks": [[p, q] for p, q in (asks or {}).items()],
    }


def _trade(ms: int, price: str, qty: str, aggressor: str = "sell") -> dict[str, Any]:
    return {
        "type": "trade",
        "event_time": _t(ms),
        "price": price,
        "quantity": qty,
        "side": aggressor,
    }


def _buy(
    price: str = "100", qty: str = "1", at_ms: int = 0, tif: float | None = None
) -> LimitOrder:
    return LimitOrder(
        order_id=f"b-{price}-{at_ms}",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal(price),
        quantity=Decimal(qty),
        submitted_at=T0 + timedelta(milliseconds=at_ms),
        time_in_force_seconds=tif,
    )


BOOK = _snapshot(0, {"100": "5", "99": "10"}, {"101": "4", "102": "8"})


def _run(events: list[dict[str, Any]], order: LimitOrder, model: FillModel) -> Any:
    return simulate_limit_orders(
        events, [order], model=model, latency_ms=10, commission_rate=Decimal("0")
    )


def test_volume_ahead_must_trade_before_the_order_fills() -> None:
    events = [BOOK, _trade(100, "100", "3"), _trade(200, "100", "3")]
    fills, report = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    assert [(f.quantity, f.filled_at) for f in fills] == [
        (Decimal("1"), T0 + timedelta(milliseconds=200))
    ]
    assert report.outcomes[0].ahead_at_entry == "5"
    touch_fills, _ = _run(events, _buy(at_ms=50), FillModel.TOUCH)
    assert touch_fills[0].filled_at == T0 + timedelta(milliseconds=100)


def test_partial_fill_when_trade_only_partly_reaches_the_order() -> None:
    events = [BOOK, _trade(100, "100", "5.4")]
    fills, report = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    assert fills[0].quantity == Decimal("0.4")
    assert report.summary()["filled_full"] == 0


def test_trade_through_fills_completely_at_the_limit_price() -> None:
    events = [BOOK, _trade(100, "99", "0.01")]
    fills, _ = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    assert (fills[0].quantity, fills[0].price, fills[0].liquidity) == (
        Decimal("1"),
        Decimal("100"),
        "maker",
    )


def test_cancellations_are_pro_rata_between_ahead_and_behind() -> None:
    # 5 ahead; 4 join behind (9 visible); 3 cancel with no trades -> ahead 5 - 3*5/9
    events = [BOOK, _diff(100, {"100": "9"}), _diff(200, {"100": "6"}), _trade(300, "100", "3.4")]
    fills, _ = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    ahead_after_cancel = Decimal(5) - Decimal(3) * Decimal(5) / Decimal(9)
    assert fills[0].quantity == Decimal("3.4") - ahead_after_cancel


def test_traded_volume_is_not_mistaken_for_cancellations() -> None:
    events = [BOOK, _trade(100, "100", "2"), _diff(150, {"100": "3"}), _trade(200, "100", "3.5")]
    fills, _ = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    assert fills[0].quantity == Decimal("0.5")  # ahead stayed 3 after the diff


def test_level_disappearing_without_trades_puts_order_first() -> None:
    events = [BOOK, _diff(100, {"100": "0"}), _trade(200, "100", "0.3")]
    fills, _ = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    assert fills[0].quantity == Decimal("0.3")


def test_trades_before_activation_do_not_count() -> None:
    events = [BOOK, _trade(5, "99", "1")]
    fills, _ = _run(events, _buy(at_ms=0), FillModel.QUEUE)  # active at 10 ms
    assert fills == []


def test_marketable_order_takes_liquidity() -> None:
    order = _buy(price="101.5", qty="5", at_ms=50)
    fills, report = _run([BOOK, _trade(100, "100", "1")], order, FillModel.QUEUE)
    assert [(f.price, f.quantity, f.liquidity) for f in fills] == [
        (Decimal("101"), Decimal("4"), "taker")
    ]
    assert report.marketable == 1


def test_time_in_force_expires_unfilled_orders() -> None:
    events = [BOOK, _trade(5000, "100", "9")]
    fills, report = _run(events, _buy(at_ms=0, tif=1), FillModel.QUEUE)
    assert fills == []
    assert report.summary()["expired_unfilled"] == 1


def test_gap_hides_levels_until_next_snapshot() -> None:
    events = [
        BOOK,
        {"type": "book_gap", "event_time": _t(60)},
        _snapshot(80, {"100": "2"}, {"101": "4"}),
        _trade(100, "100", "2.5"),
    ]
    fills, _ = _run(events, _buy(at_ms=70), FillModel.QUEUE)
    assert fills[0].quantity == Decimal("0.5")


def test_markouts_measure_mid_moves_after_the_fill() -> None:
    events = [
        BOOK,
        _trade(100, "99", "1"),
        _snapshot(900, {"98": "1"}, {"99": "1"}),
        _snapshot(70_000, {"98": "1"}, {"99": "1"}),
    ]
    _, report = _run(events, _buy(at_ms=50), FillModel.QUEUE)
    markouts = report.outcomes[0].markouts_bps
    assert markouts["1s"] is not None and markouts["1s"] < 0  # mid fell to 98.5: adverse
    assert round(markouts["10s"], 6) == round(-150.0, 6)


@st.composite
def _stream(draw: st.DrawFn) -> tuple[list[dict[str, Any]], list[LimitOrder]]:
    prices = ["99", "100", "101"]
    events: list[dict[str, Any]] = [_snapshot(0, {"99": "3", "100": "2"}, {"101": "2", "102": "3"})]
    ms = 0
    for _ in range(draw(st.integers(5, 60))):
        ms += draw(st.integers(1, 200))
        if draw(st.booleans()):
            qty = str(draw(st.integers(1, 30)) / 10)
            events.append(
                _trade(
                    ms, draw(st.sampled_from(prices)), qty, draw(st.sampled_from(["buy", "sell"]))
                )
            )
        else:
            level = draw(st.sampled_from(["99", "100"]))
            events.append(_diff(ms, {level: str(draw(st.integers(0, 40)) / 10)}))
    orders = [
        LimitOrder(
            order_id=f"o{i}",
            symbol="BTCUSDT",
            side=draw(st.sampled_from([OrderSide.BUY, OrderSide.SELL])),
            price=Decimal(draw(st.sampled_from(["99", "100", "101", "102"]))),
            quantity=Decimal(draw(st.integers(1, 20))) / 10,
            submitted_at=T0 + timedelta(milliseconds=draw(st.integers(0, ms))),
        )
        for i in range(draw(st.integers(1, 5)))
    ]
    return events, orders


@settings(max_examples=200, deadline=None)
@given(_stream())
def test_property_queue_model_never_fills_more_or_sooner_than_touch(
    data: tuple[list[dict[str, Any]], list[LimitOrder]],
) -> None:
    events, orders = data
    queue_fills, _ = simulate_limit_orders(events, orders, model=FillModel.QUEUE, latency_ms=0)
    touch_fills, _ = simulate_limit_orders(events, orders, model=FillModel.TOUCH, latency_ms=0)
    for order in orders:
        q = [f for f in queue_fills if f.order_id == order.order_id]
        t = [f for f in touch_fills if f.order_id == order.order_id]
        q_qty = sum((f.quantity for f in q), Decimal("0"))
        t_qty = sum((f.quantity for f in t), Decimal("0"))
        assert q_qty <= t_qty <= order.quantity
        if q and q[0].liquidity == "maker":
            assert t and t[0].filled_at <= q[0].filled_at


def test_cli_queue_fill(tmp_path: Any) -> None:
    import json
    import subprocess
    import sys

    book = tmp_path / "book.jsonl"
    book.write_text(
        "\n".join(json.dumps(e) for e in [BOOK, _trade(100, "100", "3"), _trade(200, "99", "1")]),
        encoding="utf-8",
    )
    orders = tmp_path / "orders.jsonl"
    orders.write_text(
        json.dumps({"order_id": "a", "side": "buy", "price": "100", "quantity": "1",
                    "submitted_at": _t(0), "time_in_force_seconds": 60}),
        encoding="utf-8",
    )
    out = tmp_path / "fills.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "market_condition_simulator", "queue-fill", "--book", str(book),
         "--orders", str(orders), "--symbol", "BTCUSDT", "--output", str(out)],
        check=True, capture_output=True, text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["model"] == "queue" and summary["filled_full"] == 1
    fill = json.loads(out.read_text(encoding="utf-8"))
    assert fill["filled_at"] == _t(200) and fill["commission"] == "0.100"
