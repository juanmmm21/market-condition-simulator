from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class ExecutionOrder:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    submitted_at: datetime

    def __post_init__(self) -> None:
        if not self.order_id:
            raise ValueError("order_id must not be empty")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        if self.submitted_at.tzinfo is None:
            raise ValueError("submitted_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BookLiquidity:
    symbol: str
    best_bid: Decimal
    best_ask: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    event_time: datetime

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.best_bid <= Decimal("0") or self.best_ask <= Decimal("0"):
            raise ValueError("best bid and ask must be positive")
        if self.best_ask < self.best_bid:
            raise ValueError("best_ask must be >= best_bid")
        if self.bid_depth < Decimal("0") or self.ask_depth < Decimal("0"):
            raise ValueError("depth values must be non-negative")
        if self.event_time.tzinfo is None:
            raise ValueError("event_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MarketTick:
    symbol: str
    price: Decimal
    event_time: datetime

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.price <= Decimal("0"):
            raise ValueError("price must be positive")
        if self.event_time.tzinfo is None:
            raise ValueError("event_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MarketConditionConfig:
    latency_ms: int = 50
    base_slippage_bps: Decimal = Decimal("2")
    impact_factor: Decimal = Decimal("0.5")
    commission_rate: Decimal = Decimal("0.001")

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.base_slippage_bps < Decimal("0"):
            raise ValueError("base_slippage_bps must be non-negative")
        if self.impact_factor < Decimal("0"):
            raise ValueError("impact_factor must be non-negative")
        if self.commission_rate < Decimal("0"):
            raise ValueError("commission_rate must be non-negative")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    reference_price: Decimal
    execution_price: Decimal
    slippage_bps: Decimal
    latency_ms: int
    submitted_at: datetime
    executed_at: datetime
    commission: Decimal

    def __post_init__(self) -> None:
        if self.reference_price <= Decimal("0") or self.execution_price <= Decimal("0"):
            raise ValueError("prices must be positive")
        if self.quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        if self.slippage_bps < Decimal("0"):
            raise ValueError("slippage_bps must be non-negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.commission < Decimal("0"):
            raise ValueError("commission must be non-negative")
        if self.submitted_at.tzinfo is None or self.executed_at.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if self.executed_at < self.submitted_at:
            raise ValueError("executed_at must be >= submitted_at")


@dataclass(frozen=True, slots=True)
class PendingExecution:
    order: ExecutionOrder
    execute_after: datetime
    book_at_submission: BookLiquidity | None


def utc_from_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def decimal_from_value(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    raise ValueError(f"{field_name} must be numeric")
