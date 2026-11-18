# market-condition-simulator

Backtest middleware that injects **realistic market frictions**: network latency and slippage from order-book liquidity constraints. Seventh module of the [quant-core-infra](https://github.com/juanmmm21/quant-core-infra) ecosystem.

Repository: [github.com/juanmmm21/market-condition-simulator](https://github.com/juanmmm21/market-condition-simulator)

---

## What it is and what problem it solves

`event-driven-backtester` executes orders at market price instantly. In reality:

- Your order takes **milliseconds** to reach the exchange (network latency)
- The price moves while you wait
- If your order is large relative to the book, you **eat through levels** and pay slippage

Ignoring this artificially inflates strategy performance. This module models those frictions explicitly and configurably.

---

## Role in quant-core-infra

```text
event-driven-backtester ──► pending orders ──► market-condition-simulator
order-book-reconstructor ──► book metrics ──┘           │
                                                             ▼
                                                   realistic execution prices
                                                             │
                                                   quant-metrics-calculator
```

It sits **between** the ideal backtester and real performance evaluation.

---

## Purpose

Demonstrates:

- Explicit execution latency modeling
- Slippage proportional to order size vs. book depth
- Prices and commissions with `Decimal` precision
- JSONL pipelines compatible with ticks, orders, and books

---

## Friction model

### Latency

An order submitted at `T₀` is not eligible for execution until `T₀ + latency_ms`. Execution occurs on the **first tick** after that instant.

### Slippage

```
slippage_bps = base_slippage_bps + impact_factor × (quantity / depth) × 10000
```

| Side | Execution price |
|------|---------------------|
| **Buy** | `reference_price × (1 + slippage_bps/10000)` |
| **Sell** | `reference_price × (1 - slippage_bps/10000)` |

- `depth` = `ask_depth` for buys, `bid_depth` for sells
- No book available → only base slippage applies

### Commission

```
commission = execution_price × quantity × commission_rate
```

---

## How it works

1. **Orders** are loaded from JSONL and enter a pending queue with `execute_after = submitted_at + latency`.
2. **Per tick:** orders whose latency window has already expired are processed.
3. **Reference price:** the tick price at the moment of execution (not at submission).
4. **Slippage:** computed using the book in effect at that instant.
5. **Result:** `ExecutionResult` with final price, slippage in bps, actual latency, and commission.

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

### Components

| Module | Responsibility |
|--------|----------------|
| `latency.py` | Execution timestamp scheduling |
| `slippage.py` | Impact model in basis points |
| `simulator.py` | Pending queue and fill orchestration |
| `ingest.py` | JSONL parsing |
| `pipeline.py` | End-to-end run |

### Technical decisions

- **Decimal** for prices, quantities, and commissions
- **Tick-driven execution** — no ticks, no fill
- **Single book snapshot** replicable across the whole series
- **Stable ordering** in the pending queue by `execute_after`

---

## Configuration: `MarketConditionConfig`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `latency_ms` | `50` | Simulated network delay |
| `base_slippage_bps` | `2` | Minimum slippage in basis points |
| `impact_factor` | `0.5` | Sensitivity to quantity/depth ratio |
| `commission_rate` | `0.001` | Commission on executed notional |

---

## Queue-position model for limit orders

Latency and slippage describe **taking** liquidity. A passive limit order **provides** it, and
whether it fills depends on how much volume is queued ahead of it. `queue.py` simulates that on a
real L2 stream (the validated output of `order-book-reconstructor replay`):

| Event | Effect on a resting order at price *p* |
|-------|------------------------------------------|
| order becomes active (`submitted_at + latency`) | joins the **back** of the queue: `ahead = visible quantity at p` (marketable orders take liquidity instead) |
| aggressive trade **at** *p* | consumes `ahead` first; the rest fills the order (partial fills allowed) |
| aggressive trade **through** *p* | the level was swept: the order fills completely at *p* |
| level decrease not explained by trades | cancellations, spread **pro-rata** over the volume ahead and behind; `ahead` never exceeds what is visible |
| `book_gap` / `book_snapshot` | levels unknown until the next snapshot; then `ahead` is clamped to the new level |
| time in force elapsed | the unfilled remainder expires |

`--model touch` is the naive baseline: an order fills completely the first time an opposite trade
touches its price. A property test checks that the queue model never fills more, or sooner, than
`touch` on random streams.

The report gives fill rate, filled-quantity ratio, median time to first fill and **markouts** (mid
1 s / 10 s / 60 s after the fill vs the fill price, in bps, positive = favourable): the gap between
the two models is the adverse selection the naive model hides.

```bash
market-condition-simulator queue-fill --book book.jsonl --orders limit_orders.jsonl \
  --symbol BTCUSDT --model queue --latency-ms 50 --output fills.jsonl --report report.json
```

Limit orders (JSONL): `order_id`, `side`, `price`, `quantity`, `submitted_at`, optional
`time_in_force_seconds`. Fills are compatible with `event-driven-backtester run --executions`.
Measured on 90 minutes of recorded BTCUSDT L2 data (2026-11-17/18, 53,975 diffs, 170,672 trades;
quant-terminal-web `scripts/l2_fill_study.py`), 358 passive orders at the touch, 0.001 BTC, 60 s
time in force, 50 ms latency:

| Model | Fill rate | Median time to first fill | Markout 60 s |
|---|---|---|---|
| `touch` | 91.6 % | 0.71 s | −0.59 bps |
| `queue` | 79.3 % | 3.91 s | −1.58 bps |

A simulation on recorded data, not live results.

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
  --base-slippage-bps 2 \
  --impact-factor 0.5 \
  --output executions.json
```

### Expected output (excerpt)

```json
{
  "order_id": "ord-1",
  "side": "buy",
  "reference_price": "100.5",
  "execution_price": "100.5204",
  "slippage_bps": "2.03",
  "latency_ms": 100,
  "commission": "0.00100520"
}
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
from datetime import UTC, datetime
from decimal import Decimal

from market_condition_simulator import (
    ExecutionOrder,
    MarketConditionConfig,
    MarketConditionSimulator,
    MarketTick,
    OrderSide,
    run_simulation_pipeline,
)

# Pipeline from files
results = run_simulation_pipeline(
    orders_path="orders.jsonl",
    ticks_path="ticks.jsonl",
    symbol="BTCUSDT",
    config=MarketConditionConfig(latency_ms=100, base_slippage_bps=Decimal("3")),
    books_path="book.jsonl",
)

# Manual simulator
sim = MarketConditionSimulator(MarketConditionConfig())
sim.submit_order(
    ExecutionOrder(
        order_id="1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.01"),
        submitted_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    ),
    book=None,
)
fills = sim.process_tick(
    MarketTick("BTCUSDT", Decimal("100.5"), datetime(2024, 1, 1, 12, 0, 0, 100_000, tzinfo=UTC)),
    book=None,
)
```

---

## Development

```bash
pytest -q
ruff check src tests
mypy src
```

---

## Roadmap

- [ ] Stochastic latency distribution (not just fixed)
- [ ] Order-book-level slippage model (walk the book)
- [ ] Integration as a plugin inside `event-driven-backtester`

---

## License

MIT
