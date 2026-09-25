"""Bounded local operator CLI. All RPC methods are read-only."""

import argparse
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import yaml

from .api import _operations
from .collect import backfill_wallet, collect_wallet_once, discover_token_accounts, stopped
from .demo import seed_demo
from .paper import simulate_paper
from .replay import replay
from .signals import MarketBar
from .solana import RpcError, SolanaRpc
from .store import Store, digest

DEFAULT_DB = "postgresql://rotation:rotation@127.0.0.1:55432/rotation"


def _db() -> Store:
    return Store(os.getenv("DATABASE_URL", DEFAULT_DB), os.getenv("ROTATION_SCHEMA", "public"))


def _print(value):
    print(json.dumps(value, default=str, sort_keys=True))


def _read(path: str):
    with open(path, encoding="utf-8") as file:
        if path.endswith(".csv"):
            return list(csv.DictReader(file))
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(file)
        return json.load(file)


def _dt(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _bars(rows):
    return [
        MarketBar(
            row["mint"],
            row["close_at"],
            row["available_at"],
            row["price_usd"],
            row["volume_usd"] or Decimal(0),
            row["liquidity_usd"],
        )
        for row in rows
    ]


def _research_config(path: str) -> dict:
    config = _read(path)
    if not isinstance(config, dict):
        raise ValueError("research config must be a mapping")
    if int(config.get("max_calls", 100)) > 1000 or int(config.get("max_calls", 100)) < 1:
        raise ValueError("max_calls outside authorized bound 1..1000")
    if int(config.get("max_pages", 2)) > 100:
        raise ValueError("max_pages > 100")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rotation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "demo-seed"):
        sub.add_parser(name)
    for name in ("import-watchlist", "import-wallets", "import-market"):
        sub.add_parser(name).add_argument("--file", required=True)
    for name in ("audit-data", "backfill", "collect", "replay", "paper"):
        sub.add_parser(name).add_argument("--config", required=True)
    sub.choices["report"] = sub.add_parser("report")
    sub.choices["report"].add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    store = _db()
    try:
        store.migrate()
        if args.command == "doctor":
            _print(
                {
                    "database": "ok",
                    "schema": store.schema,
                    "execution_enabled": False,
                    "kill_switch": stopped(),
                    "mode": os.getenv("ROTATION_MODE", "DEMO"),
                }
            )
        elif args.command == "demo-seed":
            _print(seed_demo(store))
        elif args.command == "import-watchlist":
            data = _read(args.file)
            entries = data["tokens"] if isinstance(data, dict) else data
            version = store.import_watchlist(entries, datetime.now(timezone.utc).isoformat())
            _print({"version_id": version, "tokens": len(entries)})
        elif args.command == "import-wallets":
            data = _read(args.file)
            entries = data["wallets"] if isinstance(data, dict) else data
            store.import_wallets(entries)
            _print({"wallets": len(entries)})
        elif args.command == "import-market":
            rows = _read(args.file)
            if not rows:
                raise ValueError("empty market file")
            count = 0
            for row in rows:
                if row.get("dataset", "REAL") != "REAL":
                    raise ValueError("market import accepts REAL only; DEMO is seeded separately")
                count += int(
                    store.add_market_bar(
                        row["mint"],
                        _dt(row["close_at"]),
                        _dt(row["available_at"]),
                        Decimal(row["price_usd"]),
                        Decimal(row["volume_usd"]),
                        Decimal(row["liquidity_usd"]) if row.get("liquidity_usd") else None,
                        row["source"],
                        "REAL",
                    )
                )
            _print({"dataset": "REAL", "inserted_bars": count})
        elif args.command == "audit-data":
            config = _research_config(args.config)
            address = config.get("control_address")
            if not address:
                _print({"status": "missing_control_address", "rpc_calls": 0})
            else:
                rpc = SolanaRpc(
                    config.get(
                        "rpc_url", os.getenv("SOLANA_RPC_URL", "https://api.mainnet.solana.com")
                    ),
                    max_calls=min(2, int(config.get("max_calls", 100))),
                )
                signatures = rpc.signatures(address, limit=1)
                transaction = rpc.transaction(signatures[0]["signature"]) if signatures else None
                _print(
                    {
                        "status": "tested",
                        "rpc_calls": rpc.calls,
                        "signatures": len(signatures),
                        "transaction_available": transaction is not None,
                        "address": address,
                        "research_wallet": False,
                    }
                )
        elif args.command in ("backfill", "collect"):
            config = _research_config(args.config)
            wallets = config.get("wallets") or [w["address"] for w in store.list_wallets()]
            if not wallets:
                _print({"status": "missing_wallets", "rpc_calls": 0})
                return 2
            rpc = SolanaRpc(
                config.get(
                    "rpc_url", os.getenv("SOLANA_RPC_URL", "https://api.mainnet.solana.com")
                ),
                max_calls=int(config.get("max_calls", 100)),
            )
            if args.command == "backfill":
                results = []
                for wallet in wallets[: int(config.get("max_wallets", 3))]:
                    if stopped() or rpc.calls >= rpc.max_calls:
                        break
                    accounts = discover_token_accounts(
                        rpc, wallet, int(config.get("max_token_accounts", 20))
                    )
                    for address in [wallet, *accounts]:
                        if stopped() or rpc.calls >= rpc.max_calls:
                            break
                        results.append(
                            backfill_wallet(
                                store,
                                rpc,
                                wallet,
                                address=address,
                                page_size=int(config.get("page_size", 20)),
                                max_pages=int(config.get("max_pages", 2)),
                                max_calls=rpc.max_calls - rpc.calls,
                                earliest_at=_dt(config["earliest_at"])
                                if config.get("earliest_at")
                                else None,
                            )
                        )
                _print({"status": "bounded", "rpc_calls": rpc.calls, "results": results})
            else:
                deadline = time.monotonic() + min(120, int(config.get("max_minutes", 30))) * 60
                cycles = 0
                results = []
                while not stopped() and time.monotonic() < deadline and rpc.calls < rpc.max_calls:
                    for wallet in wallets[: int(config.get("max_wallets", 3))]:
                        if rpc.calls >= rpc.max_calls or stopped():
                            break
                        results.append(
                            collect_wallet_once(
                                store, rpc, wallet, page_size=int(config.get("page_size", 20))
                            )
                        )
                    cycles += 1
                    if cycles >= int(config.get("max_cycles", 1)):
                        break
                    time.sleep(min(300, int(config.get("poll_seconds", 60))))
                _print(
                    {
                        "status": "stopped",
                        "cycles": cycles,
                        "rpc_calls": rpc.calls,
                        "results": results,
                    }
                )
        elif args.command == "replay":
            config = _read(args.config)
            dataset = config.get("dataset", "DEMO")
            if dataset not in ("DEMO", "REAL"):
                raise ValueError("replay input dataset must be DEMO or REAL")
            if dataset == "DEMO":
                seed_demo(store)
            until = _dt(config.get("until", datetime.now(timezone.utc)))
            operations = _operations(store.list_operations(until, dataset))
            bars = _bars(store.all_market_bars(until, dataset))
            result = replay(operations, bars, until)
            run_id = str(uuid.uuid4())
            payload = {
                "synthetic": dataset == "DEMO",
                "operations": len(operations),
                "market_bars": len(bars),
                "rotations": len(result.rotations),
                "signal_revisions": len(result.decisions),
                "states": [r.decision.state for r in result.decisions],
                "financial_edge": "not_evaluated",
                "historical_coverage": "insufficient" if dataset == "REAL" else "synthetic",
            }
            store.save_experiment(run_id, digest(config), dataset, "completed", payload)
            _print({"run_id": run_id, "dataset": dataset, "status": "completed", **payload})
        elif args.command == "paper":
            config = _read(args.config)
            dataset = config.get("dataset", "DEMO")
            if dataset == "DEMO":
                seed_demo(store)
            elif dataset != "REAL":
                raise ValueError("paper input dataset must be DEMO or REAL")
            until = _dt(config.get("until", datetime.now(timezone.utc)))
            operations = _operations(store.list_operations(until, dataset))
            bars = _bars(store.all_market_bars(until, dataset))
            decisions = replay(operations, bars, until).decisions
            initial_cash = Decimal(str(config.get("initial_cash", "1000")))
            simulation = simulate_paper(
                decisions,
                bars,
                initial_cash,
                allocation_fraction=Decimal(str(config.get("allocation_fraction", "0.25"))),
                fee_rate=Decimal(str(config.get("fee_rate", "0.005"))),
                impact_rate=Decimal(str(config.get("impact_rate", "0.005"))),
                network_fee=Decimal(str(config.get("network_fee", "0.01"))),
            )
            run_id = str(uuid.uuid4())
            payload = {
                "synthetic": dataset == "DEMO",
                "initial_cash": str(initial_cash),
                "ending_cash": str(simulation.book.cash),
                "holdings": {m: str(q) for m, q in simulation.book.positions.items()},
                "fees": str(simulation.book.fees),
                "filled_orders": len([o for o in simulation.orders if o["status"] == "filled"]),
                "orders": [
                    {k: v.isoformat() if isinstance(v, datetime) else v for k, v in order.items()}
                    for order in simulation.orders
                ],
                "price_model": "next available closed bar plus separate fee and impact assumptions",
                "executable_pnl": False,
                "financial_edge": "not_evaluated",
            }
            store.save_experiment(run_id, digest(config), dataset, "completed", payload)
            store.save_paper(run_id, initial_cash, simulation.book, list(simulation.orders))
            _print({"run_id": run_id, "dataset": dataset, "status": "completed", **payload})
        elif args.command == "report":
            result = store.get_experiment(args.run_id)
            if not result:
                raise ValueError("run id not found")
            _print(result)
        return 0
    except (ValueError, KeyError, RpcError) as exc:
        _print({"error": str(exc), "command": args.command})
        return 2
