"""Bounded minute-candle and pool-snapshot collection for both legs of observed pairs."""

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .market import parse_candles, parse_pool
from .r2_budget import R2BudgetExceeded
from .r2_sources import R2SourceError
from .r3_cohort import _write
from .r3_registry import ResearchRegistry


def choose_market_mints(
    root: str | Path, registry: ResearchRegistry, max_mints: int = 6
) -> list[str]:
    if not 2 <= max_mints <= 6:
        raise ValueError("market mint cap must be 2..6")
    root = Path(root)
    eligible = registry.eligible_mints(datetime.fromisoformat(registry.known_at))
    chosen: list[str] = []
    cohort = json.loads((root / "cohort.json").read_text())
    allocations = sorted(
        cohort["sequences"]["allocations"],
        key=lambda row: -(Decimal(row["amount_usd"]) if row["amount_usd"] else Decimal(0)),
    )
    for row in allocations:
        pair = (row["source_mint"], row["destination_mint"])
        if all(mint in eligible for mint in pair):
            missing = [mint for mint in pair if mint not in chosen]
            if len(chosen) + len(missing) <= max_mints:
                chosen.extend(missing)
        if len(chosen) >= max_mints:
            break
    follow_path = root / "follow-checkpoint.json"
    if follow_path.exists() and len(chosen) < max_mints:
        follow = json.loads(follow_path.read_text())
        counts = Counter(
            leg["mint"]
            for item in follow["transactions"].values()
            if item.get("kind") == "swap" and item.get("quality") == "complete"
            for leg in item.get("legs", [])
            if leg["mint"] in eligible
        )
        for mint, _ in sorted(counts.items(), key=lambda row: (-row[1], row[0])):
            if mint not in chosen and len(chosen) < max_mints:
                chosen.append(mint)
    return chosen[:max_mints]


def collect_pair_market(
    root: str | Path, registry: ResearchRegistry, http, *, max_mints: int = 6
) -> dict:
    root = Path(root)
    universe = json.loads((root.parent.parent / "config" / "r2-candidates.json").read_text())
    pools = {row["mint"]: row["primary_pool"] for row in universe["records"]}
    selected = choose_market_mints(root, registry, max_mints)
    path = root / "market-bars.json"
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "dataset": "REAL",
            "mode": "PAPER LIVE",
            "bars": [],
            "snapshots": [],
            "attempts": [],
            "stop_reason": None,
        }
    )
    state["selected_mints"] = selected
    state["stop_reason"] = None
    for mint in selected:
        pool = pools.get(mint)
        if pool is None:
            state["stop_reason"] = f"missing_exact_pool:{mint}"
            _write(path, state)
            break
        try:
            payload, receipt = http.gecko(
                f"/networks/solana/pools/{pool}/ohlcv/minute",
                {"aggregate": 1, "limit": 24, "currency": "usd", "token": mint},
            )
        except (R2SourceError, R2BudgetExceeded) as exc:
            state["stop_reason"] = str(exc)
            _write(path, state)
            break
        candles = parse_candles(
            payload, pool, mint, datetime.fromisoformat(receipt["received_at"]), 60
        )
        prior = {(row["mint"], row["close_at"], row["source_hash"]) for row in state["bars"]}
        for candle in candles:
            row = {
                "mint": mint,
                "pool": pool,
                "interval_start": candle.interval_start.isoformat(),
                "close_at": candle.close_at.isoformat(),
                "available_at": candle.received_at.isoformat(),
                "price_usd": str(candle.close_usd),
                "volume_usd": str(candle.volume_usd),
                "interval_seconds": 60,
                "volume_kind": "interval",
                "liquidity_usd": None,
                "source_hash": receipt["response_hash"],
                "source_attempt": receipt["attempt"],
            }
            key = (row["mint"], row["close_at"], row["source_hash"])
            if key not in prior:
                state["bars"].append(row)
                prior.add(key)
        state["attempts"].append(receipt["attempt"])
        _write(path, state)
        try:
            pool_payload, pool_receipt = http.gecko(f"/networks/solana/pools/{pool}")
        except (R2SourceError, R2BudgetExceeded) as exc:
            state["stop_reason"] = str(exc)
            _write(path, state)
            break
        parsed = parse_pool(
            pool_payload["data"], datetime.fromisoformat(pool_receipt["received_at"])
        )
        if mint not in {parsed.base_mint, parsed.quote_mint}:
            state["stop_reason"] = f"pool_mint_mismatch:{mint}"
            _write(path, state)
            break
        state["snapshots"].append(
            {
                "mint": mint,
                "pool": pool,
                "measured_at": None,
                "received_at": pool_receipt["received_at"],
                "pool_reserve_usd": str(parsed.reserve_usd)
                if parsed.reserve_usd is not None
                else None,
                "historical_depth_usd": None,
                "source_hash": pool_receipt["response_hash"],
                "source_attempt": pool_receipt["attempt"],
            }
        )
        state["attempts"].append(pool_receipt["attempt"])
        _write(path, state)
    if state["stop_reason"] is None:
        state["stop_reason"] = "bounded_cycle_complete"
    _write(path, state)
    return state
