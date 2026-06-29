from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from market_condition_simulator.ingest import load_books, load_orders, load_ticks
from market_condition_simulator.models import BookLiquidity, MarketConditionConfig, MarketTick
from market_condition_simulator.simulator import MarketConditionSimulator


def serialize_execution(result: object) -> dict[str, Any]:
    from market_condition_simulator.models import ExecutionResult

    if not isinstance(result, ExecutionResult):
        raise TypeError("result must be ExecutionResult")

    payload = asdict(result)
    payload["side"] = result.side.value
    payload["submitted_at"] = result.submitted_at.isoformat()
    payload["executed_at"] = result.executed_at.isoformat()
    payload["reference_price"] = str(result.reference_price)
    payload["execution_price"] = str(result.execution_price)
    payload["slippage_bps"] = str(result.slippage_bps)
    payload["quantity"] = str(result.quantity)
    payload["commission"] = str(result.commission)
    return payload


def align_books(
    ticks: list[MarketTick],
    books: list[BookLiquidity] | None,
) -> list[BookLiquidity | None]:
    if books is None:
        return [None] * len(ticks)
    if len(books) == len(ticks):
        return [book for book in books]
    if len(books) == 1:
        return [books[0]] * len(ticks)
    raise ValueError("book series must match tick count or provide a single snapshot")


def run_simulation_pipeline(
    orders_path: str,
    ticks_path: str,
    symbol: str,
    config: MarketConditionConfig,
    books_path: str | None = None,
) -> list[dict[str, Any]]:
    orders = load_orders(orders_path, default_symbol=symbol)
    ticks = load_ticks(ticks_path, default_symbol=symbol)
    books = load_books(books_path, default_symbol=symbol) if books_path else None
    aligned_books = align_books(ticks, books)

    simulator = MarketConditionSimulator(config)
    for order in orders:
        book_at_submit = _book_at_time(aligned_books, ticks, order.submitted_at)
        simulator.submit_order(order, book_at_submit)

    executions: list[dict[str, Any]] = []
    for tick, book in zip(ticks, aligned_books, strict=True):
        if tick.symbol != symbol:
            continue
        for result in simulator.process_tick(tick, book):
            executions.append(serialize_execution(result))

    if ticks:
        final_tick = ticks[-1]
        for result in simulator.flush(final_tick.event_time, final_tick.price):
            executions.append(serialize_execution(result))

    return executions


def _book_at_time(
    books: list[BookLiquidity | None],
    ticks: list[MarketTick],
    submitted_at: datetime,
) -> BookLiquidity | None:
    selected: BookLiquidity | None = None
    for tick, book in zip(ticks, books, strict=True):
        if tick.event_time <= submitted_at:
            selected = book
        else:
            break
    return selected
