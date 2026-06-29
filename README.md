# market-condition-simulator

Middleware de backtest que inyecta **fricciones realistas de mercado**: latencia de red y slippage por falta de liquidez en el libro de órdenes. Séptimo módulo del ecosistema [quant-core-infra](https://github.com/juanmmm21/quant-core-infra).

Repositorio: [github.com/juanmmm21/market-condition-simulator](https://github.com/juanmmm21/market-condition-simulator)

---

## Qué es y qué problema resuelve

`event-driven-backtester` ejecuta órdenes al precio de mercado instantáneamente. En la realidad:

- Tu orden tarda **milisegundos** en llegar al exchange (latencia de red)
- El precio se mueve mientras esperas
- Si tu orden es grande respecto al libro, **comes niveles** y pagas slippage

Ignorar esto infla artificialmente el rendimiento de las estrategias. Este módulo modela esas fricciones de forma explícita y configurable.

---

## Rol en quant-core-infra

```text
event-driven-backtester ──► órdenes pendientes ──► market-condition-simulator
order-book-reconstructor ──► métricas de libro ──┘           │
                                                             ▼
                                                   precios de ejecución realistas
                                                             │
                                                   quant-metrics-calculator
```

Se sitúa **entre** el backtester ideal y la evaluación de rendimiento real.

---

## Objetivo

Demuestra:

- Modelado explícito de latencia de ejecución
- Slippage proporcional a tamaño de orden vs profundidad del libro
- Precios y comisiones con precisión `Decimal`
- Pipelines JSONL compatibles con ticks, órdenes y libros

---

## Modelo de fricción

### Latencia

Una orden enviada en `T₀` no es elegible para ejecución hasta `T₀ + latency_ms`. La ejecución ocurre en el **primer tick** posterior a ese instante.

### Slippage

```
slippage_bps = base_slippage_bps + impact_factor × (quantity / depth) × 10000
```

| Lado | Precio de ejecución |
|------|---------------------|
| **Buy** | `reference_price × (1 + slippage_bps/10000)` |
| **Sell** | `reference_price × (1 - slippage_bps/10000)` |

- `depth` = `ask_depth` para compras, `bid_depth` para ventas
- Sin libro disponible → solo aplica slippage base

### Comisión

```
commission = execution_price × quantity × commission_rate
```

---

## Cómo funciona

1. **Órdenes** se cargan desde JSONL y entran en cola pendiente con `execute_after = submitted_at + latency`.
2. **Por cada tick:** se procesan órdenes cuya ventana de latencia ya expiró.
3. **Precio de referencia:** precio del tick en el momento de ejecución (no el de envío).
4. **Slippage:** se calcula con el libro vigente en ese instante.
5. **Resultado:** `ExecutionResult` con precio final, slippage en bps, latencia real y comisión.

---

## Arquitectura

```text
Orders JSONL
        │
        ▼
MarketConditionSimulator (cola pendiente)
        │
Ticks JSONL + Book JSONL
        │
        ▼
ExecutionResult (precio, slippage, latencia, comisión)
```

### Componentes

| Módulo | Responsabilidad |
|--------|----------------|
| `latency.py` | Scheduling de timestamp de ejecución |
| `slippage.py` | Modelo de impacto en basis points |
| `simulator.py` | Cola pendiente y orquestación de fills |
| `ingest.py` | Parsing JSONL |
| `pipeline.py` | Run end-to-end |

### Decisiones técnicas

- **Decimal** en precios, cantidades y comisiones
- **Ejecución driven por ticks** — sin ticks no hay fill
- **Snapshot único de libro** replicable en toda la serie
- **Orden estable** en cola pendiente por `execute_after`

---

## Configuración: `MarketConditionConfig`

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `latency_ms` | `50` | Retardo de red simulado |
| `base_slippage_bps` | `2` | Slippage mínimo en puntos básicos |
| `impact_factor` | `0.5` | Sensibilidad al ratio cantidad/profundidad |
| `commission_rate` | `0.001` | Comisión sobre notional ejecutado |

---

## Requisitos

- Python **3.11+**

---

## Instalación

```bash
cd market-condition-simulator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Uso CLI

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

### Salida esperada (extracto)

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

## Formatos JSONL

### Orden de ejecución

```json
{
  "order_id": "ord-1",
  "symbol": "BTCUSDT",
  "side": "buy",
  "quantity": "0.01",
  "submitted_at": "2024-01-01T12:00:00.000Z"
}
```

### Tick de mercado

```json
{
  "symbol": "BTCUSDT",
  "price": "100.5",
  "event_time": "2024-01-01T12:00:00.100Z"
}
```

### Liquidez del libro

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

## Uso programático

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

# Pipeline desde archivos
results = run_simulation_pipeline(
    orders_path="orders.jsonl",
    ticks_path="ticks.jsonl",
    symbol="BTCUSDT",
    config=MarketConditionConfig(latency_ms=100, base_slippage_bps=Decimal("3")),
    books_path="book.jsonl",
)

# Simulador manual
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

## Desarrollo

```bash
pytest -q
ruff check src tests
mypy src
```

---

## Roadmap

- [ ] Distribución estocástica de latencia (no solo fija)
- [ ] Modelo de slippage por niveles del libro (walk the book)
- [ ] Integración como plugin dentro de `event-driven-backtester`

---

## Licencia

MIT
