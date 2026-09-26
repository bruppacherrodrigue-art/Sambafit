"""Opt-in, bounded technical sampling of two exact public Solana pools."""

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .market import GeckoClient, parse_trades, select_exact_pool
from .pilot import PilotBudget, collect_corpus
from .real_corpus import JUP, USDC, WSOL, verify_manifest
from .solana import SolanaRpc


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    os.replace(temp, path)


def _load_or_fetch(path: Path, fetch) -> dict:
    if path.exists():
        payload = json.loads(path.read_text())
        return payload.get("response", payload)
    response = fetch()
    _write_json(path, {"received_at": datetime.now(timezone.utc).isoformat(), "response": response})
    return response


def run_pilot_collection(
    output: str | Path,
    *,
    gecko=None,
    rpc=None,
    per_pool: int = 30,
    rpc_url: str | None = None,
) -> dict:
    """No automatic retry, no subscription, and one persistent budget per output dir."""
    if not 1 <= per_pool <= 30:
        raise ValueError("per_pool must be 1..30")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    budget = PilotBudget(root / "budget.json", max_calls=120, max_transactions=90, max_minutes=15)
    protocol = {
        "scope": "technical_only_not_user_watchlist",
        "mints": [JUP, WSOL, USDC],
        "per_pool": per_pool,
        "pool_rule": "highest reported reserve USD among exact mint pair, then address",
        "max_calls": 120,
        "max_transactions": 90,
        "max_minutes": 15,
        "paid_spend_usd": 0,
        "started_at": budget.state["started_at"],
    }
    protocol_path = root / "protocol.json"
    if protocol_path.exists():
        existing = json.loads(protocol_path.read_text())
        if any(existing.get(key) != value for key, value in protocol.items()):
            raise ValueError("cannot change pilot protocol when resuming")
        protocol = existing
    else:
        _write_json(protocol_path, protocol)
    gecko = gecko or GeckoClient(budget, min_interval_seconds=10)
    rpc = rpc or SolanaRpc(
        rpc_url or os.getenv("SOLANA_RPC_URL", "https://api.mainnet.solana.com"),
        max_calls=90,
        min_interval_seconds=4,
        budget=budget,
    )
    pools = _load_or_fetch(root / "jup-pools.json", lambda: gecko.token_pools(JUP))
    received = datetime.fromisoformat(
        json.loads((root / "jup-pools.json").read_text())["received_at"]
    )
    sol_pool = select_exact_pool(pools["data"], JUP, WSOL, received)
    usdc_pool = select_exact_pool(pools["data"], JUP, USDC, received)
    selected = {"jup_sol": sol_pool.address, "jup_usdc": usdc_pool.address}
    if "selected_pools" in protocol and protocol["selected_pools"] != selected:
        raise ValueError("selected pools differ from the frozen protocol")
    if "selected_pools" not in protocol:
        protocol["selected_pools"] = selected
        _write_json(protocol_path, protocol)
    feeds = []
    for name, pool in (("jup-sol-trades.json", sol_pool), ("jup-usdc-trades.json", usdc_pool)):
        payload = _load_or_fetch(root / name, lambda pool=pool: gecko.trades(pool.address))
        feeds.extend(parse_trades(payload, pool.address)[:per_pool])
    references = []
    seen = set()
    for ref in feeds:
        if ref.signature not in seen:
            references.append(ref)
            seen.add(ref.signature)
    manifest = collect_corpus(references, rpc, root)
    for name, pool, mint in (
        ("jup-sol-ohlcv.json", sol_pool, JUP),
        ("sol-usd-ohlcv.json", sol_pool, WSOL),
        ("usdc-usd-ohlcv.json", usdc_pool, USDC),
    ):
        _load_or_fetch(
            root / name, lambda pool=pool, mint=mint: gecko.ohlcv(pool.address, mint, 30)
        )
    receipts = {}
    for name in (
        "jup-pools.json",
        "jup-sol-trades.json",
        "jup-usdc-trades.json",
        "jup-sol-ohlcv.json",
        "sol-usd-ohlcv.json",
        "usdc-usd-ohlcv.json",
    ):
        payload = json.loads((root / name).read_text())
        raw = payload["response"]
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
        receipts[name] = {
            "archived_at": payload["received_at"],
            "raw_sha256": sha256(canonical.encode()).hexdigest(),
            "source": "GeckoTerminal Public API",
        }
    _write_json(root / "source-receipts.json", receipts)
    verified = verify_manifest(root)
    return {
        "transactions_fetched": sum(row["status"] == "fetched" for row in manifest["records"]),
        "decoded_swaps": verified["decoded_swaps"],
        "rpc_attempts": budget.by_source.get("rpc", 0),
        "gecko_attempts": budget.by_source.get("gecko", 0),
        "attempts_total": budget.calls_used,
        "unique_transactions_attempted": budget.unique_transactions,
        "budget_started_at": budget.state["started_at"],
    }
