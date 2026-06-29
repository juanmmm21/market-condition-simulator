from __future__ import annotations

from datetime import UTC, datetime

from market_condition_simulator.latency import compute_execution_time, latency_elapsed_ms


def test_compute_execution_time_adds_latency() -> None:
    submitted = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    executed = compute_execution_time(submitted, latency_ms=50)
    assert latency_elapsed_ms(submitted, executed) == 50
