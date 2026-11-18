"""Queue-position model for passive limit orders on an L2 book.

A simulated limit order is not in the real book, so its fate depends on the real volume around
it. When the order becomes active (``submitted_at + latency``) it joins the **back** of the queue
at its price: ``ahead = visible quantity at that price``. Then, in event-time order:

* an aggressive trade **at** the order's price consumes ``ahead`` first; what is left of the trade
  fills the order;
* an aggressive trade **through** the price (a sell below a resting buy, a buy above a resting
  sell) means the whole level was taken: the order fills completely at its own price;
* a decrease of the level that trades do not explain is a **cancellation**. Cancellations are
  spread pro-rata over the volume ahead and behind (the order's place in the queue is unknown, so
  this is the neutral assumption); ``ahead`` can never exceed what is visible;
* a ``book_gap`` makes levels unknown until the next ``book_snapshot``.

``touch`` mode is the naive model it is compared against: a resting order fills completely as
soon as any opposite trade touches its price.

Input is the validated stream written by ``order-book-reconstructor replay`` (``book_snapshot``,
``book_diff``, ``book_gap`` and ``trade`` records). Trade ``side`` is the aggressor side
(Binance: ``sell`` when the buyer is the maker).
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Any

from market_condition_simulator.models import OrderSide, utc_from_iso8601

MARKOUT_HORIZONS = (1, 10, 60)


class FillModel(StrEnum):
    QUEUE = "queue"
    TOUCH = "touch"


@dataclass(frozen=True, slots=True)
class LimitOrder:
    order_id: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    submitted_at: datetime
    time_in_force_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("price and quantity must be positive")
        if self.submitted_at.tzinfo is None:
            raise ValueError("submitted_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class LimitFill:
    order_id: str
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    filled_at: datetime
    liquidity: str  # "maker" | "taker"
    model: FillModel
    commission: Decimal


@dataclass(slots=True)
class _Resting:
    order: LimitOrder
    active_at: datetime
    expires_at: datetime | None
    remaining: Decimal
    ahead: Decimal | None = None
    ahead_at_entry: Decimal | None = None
    first_fill_at: datetime | None = None
    status: str = "pending"


@dataclass(slots=True)
class OrderOutcome:
    order_id: str
    side: str
    price: str
    quantity: str
    filled: str
    status: str
    ahead_at_entry: str | None
    seconds_to_first_fill: float | None
    markouts_bps: dict[str, float | None] = field(default_factory=dict)


class _Book:
    """Price -> quantity per side, plus the best prices for the mid."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.known = False

    def load(self, bids: list[list[str]], asks: list[list[str]]) -> None:
        self.bids = {Decimal(p): Decimal(q) for p, q in bids if Decimal(q) > 0}
        self.asks = {Decimal(p): Decimal(q) for p, q in asks if Decimal(q) > 0}
        self.known = True

    def side(self, side: OrderSide) -> dict[Decimal, Decimal]:
        return self.bids if side is OrderSide.BUY else self.asks

    def mid(self) -> Decimal | None:
        if not self.known or not self.bids or not self.asks:
            return None
        return (max(self.bids) + min(self.asks)) / 2


@dataclass(slots=True)
class QueueReport:
    model: FillModel
    orders: int = 0
    filled_any: int = 0
    filled_full: int = 0
    expired: int = 0
    marketable: int = 0
    filled_quantity: Decimal = Decimal("0")
    submitted_quantity: Decimal = Decimal("0")
    outcomes: list[OrderOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        times = [o.seconds_to_first_fill for o in self.outcomes if o.seconds_to_first_fill]
        result: dict[str, Any] = {
            "model": self.model.value,
            "orders": self.orders,
            "filled_any": self.filled_any,
            "filled_full": self.filled_full,
            "expired_unfilled": self.expired,
            "marketable_on_arrival": self.marketable,
            "fill_rate": self.filled_any / self.orders if self.orders else 0.0,
            "filled_quantity_ratio": float(self.filled_quantity / self.submitted_quantity)
            if self.submitted_quantity
            else 0.0,
            "median_seconds_to_first_fill": median(times) if times else None,
        }
        for horizon in MARKOUT_HORIZONS:
            values = [
                o.markouts_bps[f"{horizon}s"]
                for o in self.outcomes
                if o.markouts_bps.get(f"{horizon}s") is not None
            ]
            clean = [v for v in values if v is not None]
            result[f"mean_markout_bps_{horizon}s"] = sum(clean) / len(clean) if clean else None
        return result


def _levels(raw: Any) -> list[list[str]]:
    return [[str(p), str(q)] for p, q in raw] if isinstance(raw, list) else []


def simulate_limit_orders(
    events: Iterable[dict[str, Any]],
    orders: Iterable[LimitOrder],
    *,
    model: FillModel,
    latency_ms: int = 50,
    commission_rate: Decimal = Decimal("0.001"),
) -> tuple[list[LimitFill], QueueReport]:
    """Run ``orders`` against the L2 ``events`` (in event-time order) under ``model``."""
    book = _Book()
    report = QueueReport(model=model)
    queue: list[_Resting] = []
    for order in sorted(orders, key=lambda o: o.submitted_at):
        active = order.submitted_at + timedelta(milliseconds=latency_ms)
        tif = order.time_in_force_seconds
        queue.append(
            _Resting(
                order=order,
                active_at=active,
                expires_at=active + timedelta(seconds=tif) if tif else None,
                remaining=order.quantity,
            )
        )
        report.orders += 1
        report.submitted_quantity += order.quantity
    waiting = list(queue)  # not yet active, sorted by activation
    resting: list[_Resting] = []
    fills: list[LimitFill] = []
    traded_at: dict[tuple[OrderSide, Decimal], Decimal] = {}
    mids: list[tuple[datetime, Decimal]] = []
    last_event: datetime | None = None

    def fill(item: _Resting, qty: Decimal, at: datetime, liquidity: str, price: Decimal) -> None:
        qty = min(qty, item.remaining)
        if qty <= 0:
            return
        item.remaining -= qty
        item.first_fill_at = item.first_fill_at or at
        fills.append(
            LimitFill(
                order_id=item.order.order_id,
                symbol=item.order.symbol,
                side=item.order.side,
                price=price,
                quantity=qty,
                filled_at=at,
                liquidity=liquidity,
                model=model,
                commission=price * qty * commission_rate,
            )
        )
        if item.remaining == 0:
            item.status = "filled"

    def activate(now: datetime) -> None:
        while waiting and waiting[0].active_at <= now:
            item = waiting.pop(0)
            if item.expires_at is not None and item.expires_at <= now:
                item.status = "expired"  # its whole life passed between two market events
                continue
            side = item.order.side
            if book.known and _marketable(book, item.order):
                report.marketable += 1
                _take_liquidity(book, item, now, fill)
                if item.remaining > 0:
                    item.status = "partially_filled_taker"
                continue
            level = book.side(side).get(item.order.price, Decimal("0")) if book.known else None
            item.ahead = level
            item.ahead_at_entry = level
            item.status = "resting"
            resting.append(item)

    def expire(now: datetime) -> None:
        for item in resting:
            if item.status == "resting" and item.expires_at and item.expires_at <= now:
                item.status = "expired"

    for event in events:
        kind = event.get("type")
        raw_time = event.get("event_time")
        if not raw_time:
            continue
        now = utc_from_iso8601(str(raw_time))
        last_event = now
        expire(now)
        activate(now)
        if kind == "book_snapshot":
            book.load(_levels(event.get("bids")), _levels(event.get("asks")))
            for item in resting:
                if item.status == "resting":
                    visible = book.side(item.order.side).get(item.order.price, Decimal("0"))
                    item.ahead = visible if item.ahead is None else min(item.ahead, visible)
            traded_at.clear()
        elif kind == "book_gap":
            book.known = False
        elif kind == "book_diff" and book.known:
            for side, key in ((OrderSide.BUY, "bids"), (OrderSide.SELL, "asks")):
                levels = book.side(side)
                for price_raw, qty_raw in _levels(event.get(key)):
                    price, new_qty = Decimal(price_raw), Decimal(qty_raw)
                    old_qty = levels.get(price, Decimal("0"))
                    traded = traded_at.pop((side, price), Decimal("0"))
                    if new_qty > 0:
                        levels[price] = new_qty
                    else:
                        levels.pop(price, None)
                    if model is FillModel.QUEUE:
                        _apply_cancellations(resting, side, price, old_qty, new_qty, traded)
        elif kind == "trade":
            price = Decimal(str(event["price"]))
            qty = Decimal(str(event["quantity"]))
            aggressor = str(event.get("side"))
            # aggressive sells hit resting buys; aggressive buys lift resting sells
            target = OrderSide.BUY if aggressor == "sell" else OrderSide.SELL
            traded_at[(target, price)] = traded_at.get((target, price), Decimal("0")) + qty
            for item in resting:
                if item.status != "resting" or item.order.side is not target:
                    continue
                limit = item.order.price
                through = price < limit if target is OrderSide.BUY else price > limit
                at_level = price == limit
                if model is FillModel.TOUCH:
                    if through or at_level:
                        fill(item, item.remaining, now, "maker", item.order.price)
                    continue
                if through:
                    fill(item, item.remaining, now, "maker", item.order.price)
                elif at_level:
                    ahead = item.ahead or Decimal("0")
                    consumed = min(qty, ahead)
                    item.ahead = ahead - consumed
                    fill(item, qty - consumed, now, "maker", item.order.price)
        mid = book.mid()
        if mid is not None and (not mids or mids[-1][1] != mid):
            mids.append((now, mid))

    for item in queue:
        if item.status == "resting":
            item.status = "open_at_end"
    _finalise(report, queue, fills, mids, last_event)
    return fills, report


def _marketable(book: _Book, order: LimitOrder) -> bool:
    if order.side is OrderSide.BUY:
        return bool(book.asks) and order.price >= min(book.asks)
    return bool(book.bids) and order.price <= max(book.bids)


def _take_liquidity(book: _Book, item: _Resting, now: datetime, fill: Any) -> None:
    order = item.order
    opposite = book.asks if order.side is OrderSide.BUY else book.bids
    prices = sorted(opposite, reverse=order.side is OrderSide.SELL)
    for price in prices:
        crosses = price <= order.price if order.side is OrderSide.BUY else price >= order.price
        if not crosses or item.remaining <= 0:
            break
        fill(item, opposite[price], now, "taker", price)


def _apply_cancellations(
    resting: list[_Resting],
    side: OrderSide,
    price: Decimal,
    old_qty: Decimal,
    new_qty: Decimal,
    traded: Decimal,
) -> None:
    others = old_qty - traded  # visible volume left after the trades since the last update
    cancelled = max(Decimal("0"), others - new_qty)
    for item in resting:
        if item.status != "resting" or item.order.side is not side or item.order.price != price:
            continue
        ahead = item.ahead or Decimal("0")
        if cancelled > 0 and others > 0:
            ahead -= cancelled * min(ahead, others) / others
        item.ahead = max(Decimal("0"), min(ahead, new_qty))


def _mid_at(
    times: list[datetime],
    mids: list[tuple[datetime, Decimal]],
    moment: datetime,
    end: datetime | None,
) -> Decimal | None:
    """Last mid at or before ``moment`` (None past the end of the data)."""
    if not mids or end is None or moment > end:
        return None
    index = bisect.bisect_right(times, moment) - 1
    return mids[index][1] if index >= 0 else None


def _finalise(
    report: QueueReport,
    queue: list[_Resting],
    fills: list[LimitFill],
    mids: list[tuple[datetime, Decimal]],
    end: datetime | None,
) -> None:
    times = [t for t, _ in mids]
    by_order: dict[str, list[LimitFill]] = {}
    for record in fills:
        by_order.setdefault(record.order_id, []).append(record)
    for item in queue:
        order = item.order
        order_fills = by_order.get(order.order_id, [])
        filled = sum((f.quantity for f in order_fills), Decimal("0"))
        report.filled_quantity += filled
        if filled > 0:
            report.filled_any += 1
        if filled == order.quantity:
            report.filled_full += 1
        if item.status == "expired" and filled == 0:
            report.expired += 1
        markouts: dict[str, float | None] = {}
        if order_fills:
            first = order_fills[0]
            for horizon in MARKOUT_HORIZONS:
                mid = _mid_at(times, mids, first.filled_at + timedelta(seconds=horizon), end)
                if mid is None:
                    markouts[f"{horizon}s"] = None
                    continue
                sign = 1 if order.side is OrderSide.BUY else -1
                markouts[f"{horizon}s"] = float(sign * (mid - first.price) / first.price) * 1e4
        report.outcomes.append(
            OrderOutcome(
                order_id=order.order_id,
                side=order.side.value,
                price=str(order.price),
                quantity=str(order.quantity),
                filled=str(filled),
                status=item.status if filled < order.quantity else "filled",
                ahead_at_entry=None if item.ahead_at_entry is None else str(item.ahead_at_entry),
                seconds_to_first_fill=(item.first_fill_at - item.active_at).total_seconds()
                if item.first_fill_at
                else None,
                markouts_bps=markouts,
            )
        )


def parse_limit_order(payload: dict[str, Any], default_symbol: str) -> LimitOrder:
    tif = payload.get("time_in_force_seconds")
    return LimitOrder(
        order_id=str(payload["order_id"]),
        symbol=str(payload.get("symbol", default_symbol)),
        side=OrderSide(str(payload["side"])),
        price=Decimal(str(payload["price"])),
        quantity=Decimal(str(payload["quantity"])),
        submitted_at=utc_from_iso8601(str(payload["submitted_at"])),
        time_in_force_seconds=float(tif) if tif is not None else None,
    )
