from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal

from market_condition_simulator.models import MarketConditionConfig
from market_condition_simulator.pipeline import run_simulation_pipeline


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

    return parser


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

    raise RuntimeError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
