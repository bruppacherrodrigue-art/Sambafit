"""Bounded local operator CLI. All RPC methods are read-only."""

import argparse
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from .api import _operations
from .collect import backfill_wallet, collect_wallet_once, discover_token_accounts, stopped
from .comparison import compare_variants
from .demo import seed_demo
from .paper import simulate_paper
from .pilot_collection import run_pilot_collection
from .r2_budget import R2Budget
from .r2_collect import collect_selected_transactions
from .r2_corpus import finalize_corpus
from .r2_follow import follow_once, refresh_follow_state
from .r2_fomo import FomoProofStore
from .r2_sequences import SequenceStore
from .r2_sources import R2Http
from .r2_universe import build_universe
from .r3_cohort import audit_selected, build_manifest, rank_verified, select_references
from .r3_market_follow import collect_pair_market
from .r3_pipeline import process_follow, replay_r2_attribution, replay_verified_corpus
from .r3_registry import ResearchRegistry
from .real_corpus import import_corpus, summarize_corpus, verify_manifest
from .replay import replay
from .research import price_operations, study_events
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
    for name in ("pilot-audit", "pilot-import", "pilot-verify"):
        sub.add_parser(name).add_argument("--corpus", required=True)
    pilot_collect = sub.add_parser("pilot-collect")
    pilot_collect.add_argument("--output", required=True)
    pilot_collect.add_argument("--per-pool", type=int, default=30)
    pilot_collect.add_argument("--rpc-url")
    for name in ("r2-universe", "r2-verify", "r2-sequences", "r2-budget"):
        sub.add_parser(name).add_argument("--root", default="data/r2-20260926")
    r2_collect = sub.add_parser("r2-collect-tx")
    r2_collect.add_argument("--root", default="data/r2-20260926")
    r2_collect.add_argument("--limit", type=int, default=10)
    r2_follow = sub.add_parser("r2-follow-once")
    r2_follow.add_argument("--root", default="data/r2-20260926")
    r2_follow.add_argument("--wallets", type=int, default=3)
    r2_follow.add_argument("--pools", type=int, default=2)
    r2_follow.add_argument("--transactions", type=int, default=10)
    proof_import = sub.add_parser("r2-fomo-import")
    proof_import.add_argument("--root", default="data/r2-20260926")
    proof_import.add_argument("--file", required=True)
    proof_review = sub.add_parser("r2-fomo-review")
    proof_review.add_argument("--root", default="data/r2-20260926")
    proof_review.add_argument("--id", required=True)
    proof_review.add_argument("--reviewer", required=True)
    proof_review.add_argument("--decision", choices=("verified", "rejected"), required=True)
    proof_review.add_argument("--comment", required=True)
    for name in (
        "r3-select",
        "r3-audit",
        "r3-cohort",
        "r3-replay",
        "r3-process-follow",
        "r3-refresh-follow",
        "r3-budget",
        "r3-manifest",
    ):
        command = sub.add_parser(name)
        command.add_argument("--r2-root", default="data/r2-20260926")
        command.add_argument("--root", default="data/r3-20260927")
        command.add_argument("--registry", default="config/r3-universe.json")
    sub.choices["r3-audit"].add_argument("--max-new-calls", type=int, default=24)
    r3_follow = sub.add_parser("r3-follow-once")
    r3_follow.add_argument("--root", default="data/r3-20260927")
    r3_follow.add_argument("--wallets", type=int, default=4)
    r3_follow.add_argument("--pages", type=int, default=2)
    r3_follow.add_argument("--transactions", type=int, default=8)
    r3_market = sub.add_parser("r3-market-follow")
    r3_market.add_argument("--root", default="data/r3-20260927")
    r3_market.add_argument("--registry", default="config/r3-universe.json")
    r3_market.add_argument("--max-mints", type=int, default=6)
    sub.choices["report"] = sub.add_parser("report")
    sub.choices["report"].add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "r3-budget":
        _print(R2Budget(Path(args.root) / "budget.json").snapshot())
        return 0
    if args.command == "r3-manifest":
        result = build_manifest(args.root)
        _print({"transactions": len(result["transactions"]), "attempts": result["calls_used"]})
        return 0
    if args.command == "r3-select":
        registry = ResearchRegistry.load(args.registry)
        selection = select_references(args.r2_root, registry)
        root = Path(args.root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "preselection.json").write_text(
            json.dumps(selection, indent=2, sort_keys=True) + "\n"
        )
        _print(
            {
                "references": len(selection["references"]),
                "above_threshold": selection["eligible_references_above_threshold"],
                "window": selection["common_window"],
                "scope": selection["scope"],
            }
        )
        return 0
    if args.command == "r3-audit":
        if not 1 <= args.max_new_calls <= 24:
            raise ValueError("R3 audit call cap must be 1..24")
        root = Path(args.root)
        with R2Budget(root / "budget.json").session(
            "r3-cohort-audit",
            max_calls=30,
            max_seconds=300,
            phase="cohort_audit",
            phase_max_calls=30,
            phase_max_active_seconds=300,
        ) as session:
            http = R2Http(
                session,
                root / "source",
                rpc_url=os.getenv("SOLANA_RPC_URL", "https://solana.publicnode.com"),
            )
            result = audit_selected(args.r2_root, root, http, max_new_calls=args.max_new_calls)
        _print(
            {
                "new_calls": result["new_rpc_calls_last_run"],
                "statuses": {
                    status: sum(row["attribution_status"] == status for row in result["references"])
                    for status in sorted(
                        {row["attribution_status"] for row in result["references"]}
                    )
                },
            }
        )
        return 0
    if args.command == "r3-cohort":
        result = rank_verified(args.root, ResearchRegistry.load(args.registry))
        _print(
            {
                "strict_swaps": result["strict_swap_count"],
                "wallets": len(result["wallets"]),
                "qualified_wallets": result["qualified_wallets"],
                "scope": result["scope"],
            }
        )
        return 0
    if args.command == "r3-replay":
        registry = ResearchRegistry.load(args.registry)
        comparison = replay_r2_attribution(args.r2_root, args.root, registry)
        result = replay_verified_corpus(args.root, args.root, registry, r2_root=args.r2_root)
        _print(
            {
                "dataset": "REAL",
                "mode": "REPLAY",
                "r2_allocations": comparison["r2_allocation_count"],
                "r3_r2_allocations": comparison["r3_allocation_count"],
                "verified_operations": result["verified_operations"],
                "target_rotations": result["target_rotations"],
                "pairs_evaluated": result["pairs_evaluated"],
                "decisions": len(result["decisions"]),
                "financial_edge": result["financial_edge"],
            }
        )
        return 0
    if args.command == "r3-process-follow":
        result = process_follow(args.root, ResearchRegistry.load(args.registry))
        _print(
            {
                "dataset": result["dataset"],
                "mode": result["mode"],
                "stages": result["stages"],
                "missing_transitions": result["missing_transitions"],
                "execution_status": result["execution_status"],
            }
        )
        return 0
    if args.command == "r3-refresh-follow":
        result = refresh_follow_state(args.root)
        _print(
            {
                "transactions": len(result["transactions"]),
                "incomplete_enrichment": len(result["enrichment_queue"]),
                "calls": 0,
            }
        )
        return 0
    if args.command == "r3-follow-once":
        root = Path(args.root)
        if (
            not 1 <= args.wallets <= 10
            or not 0 <= args.pages <= 2
            or not 0 <= args.transactions <= 12
        ):
            raise ValueError("R3 prospective cycle exceeds preregistered bounds")
        with R2Budget(root / "budget.json").session(
            "r3-prospective-follow",
            max_calls=40,
            max_seconds=300,
            phase="prospective_follow",
            phase_max_calls=40,
            phase_max_active_seconds=300,
        ) as session:
            http = R2Http(
                session,
                root / "source",
                rpc_url=os.getenv("SOLANA_RPC_URL", "https://solana.publicnode.com"),
            )
            state = follow_once(
                root,
                http,
                wallets_limit=args.wallets,
                pools_limit=0,
                transactions_limit=args.transactions,
                pages_limit=args.pages,
            )
        _print(
            {
                "stop_reason": state["stop_reason"],
                "transactions": len(state["transactions"]),
                "gaps": len(state["gaps"]),
                "queued": sum(
                    len(w.get("pending_signatures", [])) for w in state["wallets"].values()
                ),
            }
        )
        return 0
    if args.command == "r3-market-follow":
        root = Path(args.root)
        registry = ResearchRegistry.load(args.registry)
        with R2Budget(root / "budget.json").session(
            "r3-pair-market",
            max_calls=20,
            max_seconds=180,
            phase="market_follow",
            phase_max_calls=20,
            phase_max_active_seconds=180,
        ) as session:
            http = R2Http(session, root / "source")
            state = collect_pair_market(root, registry, http, max_mints=args.max_mints)
        _print(
            {
                "selected_mints": state["selected_mints"],
                "closed_bars": len(state["bars"]),
                "snapshots": len(state["snapshots"]),
                "stop_reason": state["stop_reason"],
            }
        )
        return 0
    if args.command == "r2-budget":
        _print(R2Budget(Path(args.root) / "budget.json").snapshot())
        return 0
    if args.command == "r2-universe":
        result = build_universe(args.root)
        _print(result)
        return 0
    if args.command == "r2-verify":
        result = finalize_corpus(args.root)
        _print(result["summary"])
        return 0
    if args.command == "r2-sequences":
        root = Path(args.root)
        corpus = json.loads((root / "cohort.json").read_text())
        with SequenceStore(root / "sequences.sqlite") as sequences:
            inserted = sequences.add(corpus["events"])
            state = sequences.snapshot()
        _print({"inserted": inserted, "state": state})
        return 0
    if args.command == "r2-collect-tx":
        root = Path(args.root)
        with R2Budget(root / "budget.json").session(
            "cli_tx_followup", max_calls=min(args.limit, 100), max_seconds=120
        ) as session:
            _print(
                collect_selected_transactions(
                    root, R2Http(session, root / "source", min_interval_seconds=4), limit=args.limit
                )
            )
        return 0
    if args.command == "r2-follow-once":
        root = Path(args.root)
        calls = args.wallets + args.pools + args.transactions
        if not 1 <= calls <= 100:
            raise ValueError("R2 follow cycle exceeds local call bound")
        with R2Budget(root / "budget.json").session(
            "cli_follow_once", max_calls=calls, max_seconds=180
        ) as session:
            result = follow_once(
                root,
                R2Http(session, root / "source", min_interval_seconds=4),
                wallets_limit=args.wallets,
                pools_limit=args.pools,
                transactions_limit=args.transactions,
            )
            _print(
                {
                    "wallets_checked": len(result["wallets"]),
                    "transactions": len(result["transactions"]),
                    "market_snapshots": len(result["market_snapshots"]),
                    "gaps": len(result["gaps"]),
                    "stop_reason": result["stop_reason"],
                }
            )
        return 0
    if args.command == "r2-fomo-import":
        with FomoProofStore(Path(args.root) / "fomo-proofs.sqlite") as proofs:
            data = _read(args.file)
            _print(
                [proofs.add(row) for row in (data if isinstance(data, list) else data["proofs"])]
            )
        return 0
    if args.command == "r2-fomo-review":
        with FomoProofStore(Path(args.root) / "fomo-proofs.sqlite") as proofs:
            _print(
                proofs.review(
                    args.id,
                    reviewer=args.reviewer,
                    decision=args.decision,
                    review_comment=args.comment,
                )
            )
        return 0
    if args.command == "pilot-collect":
        _print(run_pilot_collection(args.output, per_pool=args.per_pool, rpc_url=args.rpc_url))
        return 0
    if args.command == "pilot-audit":
        result = summarize_corpus(args.corpus)
        _print({key: value for key, value in result.items() if key != "audits"})
        return 0
    if args.command == "pilot-verify":
        _print(verify_manifest(args.corpus))
        return 0
    store = _db()
    try:
        store.migrate()
        if args.command == "pilot-import":
            _print(import_corpus(store, args.corpus))
        elif args.command == "doctor":
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
                                swap_program_ids=set(config.get("swap_program_ids", [])),
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
                                store,
                                rpc,
                                wallet,
                                page_size=int(config.get("page_size", 20)),
                                swap_program_ids=set(config.get("swap_program_ids", [])),
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
            operations = price_operations(operations, bars)
            registry = (
                ResearchRegistry.load(config.get("registry_file", "config/r3-universe.json"))
                if dataset == "REAL"
                else None
            )
            registry_mints = registry.eligible_mints(until) if registry else None
            requested_mints = set(config["eligible_mints"]) if "eligible_mints" in config else None
            eligible_mints = (
                registry_mints & requested_mints
                if registry_mints is not None and requested_mints is not None
                else registry_mints
                if registry_mints is not None
                else requested_mints
            )
            result = replay(
                operations,
                bars,
                until,
                stable_mints=set(
                    config.get("stable_mints", ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"])
                ),
                reserve_mints=set(
                    config.get("reserve_mints", ["So11111111111111111111111111111111111111112"])
                ),
                eligible_mints=eligible_mints,
                eligible_wallets=set(config["eligible_wallets"])
                if "eligible_wallets" in config
                else None,
                mint_known_at={
                    mint: _dt(value) for mint, value in config.get("mint_known_at", {}).items()
                },
                wallet_known_at={
                    wallet: _dt(value)
                    for wallet, value in config.get("wallet_known_at", {}).items()
                },
                registry=registry,
            )
            study = study_events(
                result, bars, tuple(int(x) for x in config.get("horizons_minutes", [60, 240, 1440]))
            )
            universe = {bar.mint for bar in bars}
            if eligible_mints is not None:
                universe &= eligible_mints
            comparison = (
                compare_variants(
                    result.rotations,
                    bars,
                    Decimal(str(config.get("initial_cash", "1000"))),
                    universe,
                )
                if universe
                else {
                    name: {"status": "not_evaluated_no_market_data"}
                    for name in ("basket", "market_only", "wallets_only", "combined")
                }
            )
            run_id = str(uuid.uuid4())
            config_hash = digest(config)
            revision_dataset = "DEMO" if dataset == "DEMO" else "REPLAY"
            for record in result.decisions:
                store.record_decision(
                    record.pair,
                    record.at,
                    record.decision.state,
                    record.decision.quality,
                    record.decision.score,
                    dict(record.decision.components),
                    config_hash,
                    revision_dataset,
                    list(record.decision.reasons),
                )
            payload = {
                "synthetic": dataset == "DEMO",
                "operations": len(operations),
                "market_bars": len(bars),
                "rotations": len(result.rotations),
                "aggregate_flows": len(result.aggregate_flows),
                "signal_revisions": len(result.decisions),
                "states": [r.decision.state for r in result.decisions],
                "event_study": study,
                "comparison": comparison,
                "financial_edge": "not_evaluated",
                "historical_coverage": "insufficient" if dataset == "REAL" else "synthetic",
            }
            store.save_experiment(run_id, config_hash, dataset, "completed", payload)
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
            decisions = replay(
                price_operations(operations, bars),
                bars,
                until,
                stable_mints={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
                reserve_mints={"So11111111111111111111111111111111111111112"},
            ).decisions
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
