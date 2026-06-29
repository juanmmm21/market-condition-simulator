from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from market_condition_simulator.models import MarketConditionConfig
from market_condition_simulator.pipeline import run_simulation_pipeline


def test_pipeline_runs_sample_files() -> None:
    root = Path(__file__).resolve().parents[1]
    executions = run_simulation_pipeline(
        orders_path=str(root / "samples" / "btcusdt_orders.jsonl"),
        ticks_path=str(root / "samples" / "btcusdt_ticks.jsonl"),
        symbol="BTCUSDT",
        config=MarketConditionConfig(latency_ms=50),
        books_path=str(root / "samples" / "btcusdt_book.jsonl"),
    )
    assert len(executions) == 2
    buy = executions[0]
    sell = executions[1]
    assert buy["side"] == "buy"
    assert sell["side"] == "sell"
    assert Decimal(buy["execution_price"]) > Decimal(buy["reference_price"])
    assert Decimal(sell["execution_price"]) < Decimal(sell["reference_price"])
