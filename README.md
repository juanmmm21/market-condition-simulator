# market-condition-simulator

**Backtest middleware** that injects realistic market frictions: network latency and order book slippage. Seventh module of the [quant-core-infra](https://github.com/juanmmm21/quant-core-infra) ecosystem, designed to sit between `event-driven-backtester` and production-grade execution models.

Repository: [github.com/juanmmm21/market-condition-simulator](https://github.com/juanmmm21/market-condition-simulator)

---

## Objective

This project demonstrates:

- Explicit latency modeling for delayed order execution
- Liquidity-aware slippage based on order size vs book depth
- Decimal-safe execution pricing and commission calculation
- JSONL pipelines compatible with ticks, orders and book metrics

---

## Friction model

| Component | Behavior |
|-----------|----------|
| **Latency** | Orders become eligible `latency_ms` after submission |
| **Base slippage** | Fixed adverse price shift in basis points |
| **Impact slippage** | Additional bps proportional to `quantity / depth` |
| **Commission** | Applied on executed notional |

Buy orders execute above the reference price; sell orders execute below it.

---

## Architecture

```text
Orders JSONL
        │
        ▼
MarketConditionSimulator (pending queue)
        │
Ticks JSONL + Book JSONL
        │
        ▼
ExecutionResult (price, slippage, latency, commission)
```

### Core components

| Module | Responsibility |
|--------|----------------|
| `latency.py` | Execution timestamp scheduling |
| `slippage.py` | Basis-point impact model |
| `simulator.py` | Pending queue and fill orchestration |
| `ingest.py` | JSONL parsing for orders, ticks, books |
| `pipeline.py` | End-to-end simulation run |

### Technical decisions

- **Decimal** for all prices, quantities and commissions
- **Tick-driven execution** — fills occur on the first tick after latency expires
- **Depth-aware impact** — larger orders relative to ask/bid depth pay more slippage
- **Single-book snapshot** can be broadcast across the tick series

---

## Requirements

- Python **3.11+**

---

## Installation

```bash
cd market-condition-simulator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## CLI usage

```bash
market-condition-simulator run \
  --orders samples/btcusdt_orders.jsonl \
  --ticks samples/btcusdt_ticks.jsonl \
  --books samples/btcusdt_book.jsonl \
  --symbol BTCUSDT \
  --latency-ms 50 \
  --base-slippage-bps 2
```

---

## JSONL formats

### Execution order

```json
{
  "order_id": "ord-1",
  "symbol": "BTCUSDT",
  "side": "buy",
  "quantity": "0.01",
  "submitted_at": "2024-01-01T12:00:00.000Z"
}
```

### Market tick

```json
{
  "symbol": "BTCUSDT",
  "price": "100.5",
  "event_time": "2024-01-01T12:00:00.100Z"
}
```

### Book liquidity

```json
{
  "symbol": "BTCUSDT",
  "best_bid": "99.9",
  "best_ask": "100.1",
  "bid_depth": "5.0",
  "ask_depth": "2.0",
  "event_time": "2024-01-01T12:00:00.000Z"
}
```

---

## Programmatic usage

```python
from decimal import Decimal

from market_condition_simulator import (
    ExecutionOrder,
    MarketConditionConfig,
    MarketConditionSimulator,
    OrderSide,
    run_simulation_pipeline,
)

results = run_simulation_pipeline(
    orders_path="orders.jsonl",
    ticks_path="ticks.jsonl",
    symbol="BTCUSDT",
    config=MarketConditionConfig(latency_ms=50),
)

simulator = MarketConditionSimulator(MarketConditionConfig())
```

---

## Development

```bash
pytest -q
ruff check src tests
mypy src
```

---

## Ecosystem integration

```text
event-driven-backtester ──► orders JSONL ──► market-condition-simulator ──► realistic fills
order-book-reconstructor ──► book metrics ──┘
```

---

## License

MIT
