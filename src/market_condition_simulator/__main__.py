from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterator
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from market_condition_simulator.models import MarketConditionConfig
from market_condition_simulator.pipeline import run_simulation_pipeline
from market_condition_simulator.queue import FillModel, parse_limit_order, simulate_limit_orders


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Middleware de simulación con latencia de red y slippage del libro.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Simula ejecución realista de órdenes JSONL.")
    run.add_argument("--orders", required=True)
    run.add_argument("--ticks", required=True)
    run.add_argument("--books", default=None)
    run.add_argument("--symbol", required=True)
    run.add_argument("--latency-ms", type=int, default=50)
    run.add_argument("--base-slippage-bps", default="2")
    run.add_argument("--impact-factor", default="0.5")
    run.add_argument("--commission-rate", default="0.001")
    run.add_argument("--output", default=None)

    queue = subparsers.add_parser(
        "queue-fill",
        help="Simula órdenes límite pasivas con posición en la cola sobre un libro L2.",
    )
    queue.add_argument("--book", required=True, help="Flujo L2 validado (reconstructor replay).")
    queue.add_argument("--orders", required=True, help="Órdenes límite JSONL.")
    queue.add_argument("--symbol", required=True)
    queue.add_argument("--model", choices=[m.value for m in FillModel], default="queue")
    queue.add_argument("--latency-ms", type=int, default=50)
    queue.add_argument("--commission-rate", default="0.001")
    queue.add_argument("--output", required=True, help="Fills JSONL.")
    queue.add_argument("--report", default=None, help="Resumen JSON (por defecto stdout).")

    return parser


def _run_queue(args: argparse.Namespace) -> None:
    from pathlib import Path

    def records(path: str) -> Iterator[dict[str, Any]]:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)

    orders = [parse_limit_order(row, args.symbol) for row in records(args.orders)]
    fills, report = simulate_limit_orders(
        records(args.book),
        orders,
        model=FillModel(args.model),
        latency_ms=args.latency_ms,
        commission_rate=Decimal(args.commission_rate),
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        for item in fills:
            handle.write(
                json.dumps(
                    {
                        "order_id": item.order_id,
                        "symbol": item.symbol,
                        "side": item.side.value,
                        "price": str(item.price),
                        "quantity": str(item.quantity),
                        "commission": str(item.commission),
                        "filled_at": item.filled_at.isoformat(),
                        "liquidity": item.liquidity,
                        "model": item.model.value,
                    }
                )
                + "\n"
            )
    summary = report.summary()
    summary["outcomes"] = [asdict(outcome) for outcome in report.outcomes]
    rendered = json.dumps(summary, indent=2)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if args.command == "run":
        config = MarketConditionConfig(
            latency_ms=args.latency_ms,
            base_slippage_bps=Decimal(args.base_slippage_bps),
            impact_factor=Decimal(args.impact_factor),
            commission_rate=Decimal(args.commission_rate),
        )
        executions = run_simulation_pipeline(
            orders_path=args.orders,
            ticks_path=args.ticks,
            symbol=args.symbol,
            config=config,
            books_path=args.books,
        )
        rendered = json.dumps(executions, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.write("\n")
            logging.getLogger(__name__).info(
                "wrote %s executions to %s",
                len(executions),
                args.output,
            )
            return
        print(rendered)
        return

    if args.command == "queue-fill":
        _run_queue(args)
        return

    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
