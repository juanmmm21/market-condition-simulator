from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from market_condition_simulator.models import (
    BookLiquidity,
    ExecutionOrder,
    ExecutionResult,
    MarketTick,
)


class ExecutionMiddleware(Protocol):
    def submit_order(
        self,
        order: ExecutionOrder,
        book: BookLiquidity | None,
    ) -> None:
        ...

    def process_tick(
        self,
        tick: MarketTick,
        book: BookLiquidity | None,
    ) -> list[ExecutionResult]:
        ...

    def flush(self, final_time: datetime, reference_price: Decimal) -> list[ExecutionResult]:
        ...
