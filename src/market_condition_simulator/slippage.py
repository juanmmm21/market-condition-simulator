from __future__ import annotations

from decimal import Decimal

from market_condition_simulator.models import BookLiquidity, MarketConditionConfig, OrderSide


def calculate_slippage_bps(
    side: OrderSide,
    quantity: Decimal,
    book: BookLiquidity | None,
    config: MarketConditionConfig,
) -> Decimal:
    if quantity <= Decimal("0"):
        raise ValueError("quantity must be positive")

    depth = _relevant_depth(side, book)
    impact_bps = Decimal("0")
    if depth > Decimal("0"):
        utilization = quantity / depth
        impact_bps = config.impact_factor * utilization * Decimal("10000")

    return config.base_slippage_bps + impact_bps


def apply_slippage(
    reference_price: Decimal,
    side: OrderSide,
    slippage_bps: Decimal,
) -> Decimal:
    if reference_price <= Decimal("0"):
        raise ValueError("reference_price must be positive")
    if slippage_bps < Decimal("0"):
        raise ValueError("slippage_bps must be non-negative")

    ratio = slippage_bps / Decimal("10000")
    if side is OrderSide.BUY:
        return reference_price * (Decimal("1") + ratio)
    return reference_price * (Decimal("1") - ratio)


def _relevant_depth(side: OrderSide, book: BookLiquidity | None) -> Decimal:
    if book is None:
        return Decimal("0")
    if side is OrderSide.BUY:
        return book.ask_depth
    return book.bid_depth
