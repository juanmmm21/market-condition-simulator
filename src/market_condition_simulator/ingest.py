from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from market_condition_simulator.models import (
    BookLiquidity,
    ExecutionOrder,
    MarketTick,
    OrderSide,
    decimal_from_value,
    utc_from_iso8601,
)


def load_orders(path: str | Path, default_symbol: str) -> list[ExecutionOrder]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"orders file not found: {file_path}")

    orders: list[ExecutionOrder] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json on line {line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            orders.append(parse_execution_order(payload, default_symbol))

    if not orders:
        raise ValueError("orders file is empty")
    return orders


def load_ticks(path: str | Path, default_symbol: str) -> list[MarketTick]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"ticks file not found: {file_path}")

    ticks: list[MarketTick] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json on line {line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            ticks.append(parse_market_tick(payload, default_symbol))

    if not ticks:
        raise ValueError("ticks file is empty")
    return ticks


def load_books(path: str | Path, default_symbol: str) -> list[BookLiquidity]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"book file not found: {file_path}")

    books: list[BookLiquidity] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json on line {line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            books.append(parse_book_liquidity(payload, default_symbol))

    return books


def parse_execution_order(payload: dict[str, Any], default_symbol: str) -> ExecutionOrder:
    required = ("order_id", "side", "quantity", "submitted_at")
    for field in required:
        if field not in payload:
            raise ValueError(f"missing required field: {field}")

    symbol = str(payload.get("symbol", default_symbol))
    if not symbol:
        raise ValueError("symbol must not be empty")

    side = _parse_side(str(payload["side"]))
    return ExecutionOrder(
        order_id=str(payload["order_id"]),
        symbol=symbol,
        side=side,
        quantity=decimal_from_value(payload["quantity"], "quantity"),
        submitted_at=utc_from_iso8601(str(payload["submitted_at"])),
    )


def parse_market_tick(payload: dict[str, Any], default_symbol: str) -> MarketTick:
    if "price" not in payload or "event_time" not in payload:
        raise ValueError("tick requires price and event_time")

    symbol = str(payload.get("symbol", default_symbol))
    return MarketTick(
        symbol=symbol,
        price=decimal_from_value(payload["price"], "price"),
        event_time=utc_from_iso8601(str(payload["event_time"])),
    )


def parse_book_liquidity(payload: dict[str, Any], default_symbol: str) -> BookLiquidity:
    required = ("best_bid", "best_ask", "bid_depth", "ask_depth", "event_time")
    for field in required:
        if field not in payload:
            raise ValueError(f"missing required field: {field}")

    symbol = str(payload.get("symbol", default_symbol))
    spread = payload.get("spread")
    if spread is not None:
        _ = decimal_from_value(spread, "spread")

    return BookLiquidity(
        symbol=symbol,
        best_bid=decimal_from_value(payload["best_bid"], "best_bid"),
        best_ask=decimal_from_value(payload["best_ask"], "best_ask"),
        bid_depth=decimal_from_value(payload["bid_depth"], "bid_depth"),
        ask_depth=decimal_from_value(payload["ask_depth"], "ask_depth"),
        event_time=utc_from_iso8601(str(payload["event_time"])),
    )


def _parse_side(value: str) -> OrderSide:
    try:
        return OrderSide(value)
    except ValueError as exc:
        raise ValueError(f"unsupported order side: {value}") from exc
