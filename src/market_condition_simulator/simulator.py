from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from market_condition_simulator.latency import compute_execution_time, latency_elapsed_ms
from market_condition_simulator.models import (
    BookLiquidity,
    ExecutionOrder,
    ExecutionResult,
    MarketConditionConfig,
    MarketTick,
    PendingExecution,
)
from market_condition_simulator.slippage import apply_slippage, calculate_slippage_bps


class MarketConditionSimulator:
    """Middleware que retrasa ejecuciones y aplica slippage según liquidez del libro."""

    def __init__(self, config: MarketConditionConfig) -> None:
        self._config = config
        self._pending: list[PendingExecution] = []
        self._last_price: Decimal | None = None
        self._last_book: BookLiquidity | None = None

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def submit_order(
        self,
        order: ExecutionOrder,
        book: BookLiquidity | None,
    ) -> None:
        execute_after = compute_execution_time(order.submitted_at, self._config.latency_ms)
        self._pending.append(
            PendingExecution(
                order=order,
                execute_after=execute_after,
                book_at_submission=book,
            )
        )
        self._pending.sort(key=lambda item: item.execute_after)

    def process_tick(
        self,
        tick: MarketTick,
        book: BookLiquidity | None,
    ) -> list[ExecutionResult]:
        if tick.price <= Decimal("0"):
            raise ValueError("tick price must be positive")
        self._last_price = tick.price
        if book is not None:
            self._last_book = book
        return self._process_ready(tick.event_time, tick.price, book or self._last_book)

    def flush(self, final_time: datetime, reference_price: Decimal) -> list[ExecutionResult]:
        if reference_price <= Decimal("0"):
            raise ValueError("reference_price must be positive")
        if final_time.tzinfo is None:
            raise ValueError("final_time must be timezone-aware")
        return self._process_ready(final_time, reference_price, self._last_book)

    def _process_ready(
        self,
        current_time: datetime,
        reference_price: Decimal,
        book: BookLiquidity | None,
    ) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        remaining: list[PendingExecution] = []

        for pending in self._pending:
            if pending.execute_after <= current_time:
                results.append(
                    self._execute_order(
                        pending,
                        reference_price,
                        book,
                        current_time,
                    )
                )
            else:
                remaining.append(pending)

        self._pending = remaining
        return results

    def _execute_order(
        self,
        pending: PendingExecution,
        reference_price: Decimal,
        book: BookLiquidity | None,
        executed_at: datetime,
    ) -> ExecutionResult:
        order = pending.order
        liquidity_book = book or pending.book_at_submission
        slippage_bps = calculate_slippage_bps(
            order.side,
            order.quantity,
            liquidity_book,
            self._config,
        )
        execution_price = apply_slippage(reference_price, order.side, slippage_bps)
        notional = execution_price * order.quantity
        commission = notional * self._config.commission_rate

        return ExecutionResult(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            reference_price=reference_price,
            execution_price=execution_price,
            slippage_bps=slippage_bps,
            latency_ms=latency_elapsed_ms(order.submitted_at, executed_at),
            submitted_at=order.submitted_at,
            executed_at=executed_at,
            commission=commission,
        )
