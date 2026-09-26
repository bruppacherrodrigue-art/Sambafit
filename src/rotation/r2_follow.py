"""One coordinated, bounded R2 follow cycle. No background loop or orders."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .market import parse_pool
from .r2_budget import R2BudgetExceeded
from .r2_collect import _archived
from .r2_decode import R2Decoder
from .r2_sources import R2SourceError


def _save(path: Path, value: dict):
    if "transactions" in value and "wallets" in value:
        inventories = {}
        for item in value["transactions"].values():
            if item.get("status") != "fetched" or item.get("kind") == "failed":
                continue
            wallet = inventories.setdefault(item["wallet"], {})
            for leg in item.get("legs", []):
                wallet[leg["mint"]] = wallet.get(leg["mint"], 0) + int(leg["delta_base"])
        value["observable_inventory_delta_base"] = {
            w: {m: str(q) for m, q in legs.items()} for w, legs in inventories.items()
        }
        value["opening_positions_unknown"] = True
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def follow_once(
    root: str | Path,
    http,
    *,
    wallets_limit: int = 3,
    pools_limit: int = 2,
    transactions_limit: int = 10,
) -> dict:
    if (
        not 1 <= wallets_limit <= 40
        or not 1 <= pools_limit <= 12
        or not 0 <= transactions_limit <= 100
    ):
        raise ValueError("invalid bounded R2 cycle limits")
    root = Path(root)
    cohort = json.loads((root / "cohort.json").read_text())
    universe = json.loads((root.parent.parent / "config" / "r2-candidates.json").read_text())
    pools = [x for x in universe["records"] if x["status"] == "research_candidate"]
    path = root / "follow-checkpoint.json"
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "wallets": {},
            "transactions": {},
            "market_snapshots": [],
            "gaps": [],
            "next_pool_index": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stop_reason": None,
        }
    )
    state["stop_reason"] = None
    fetched = 0
    decoder = R2Decoder()
    for _ in range(min(pools_limit, len(pools))):
        index = state["next_pool_index"] % len(pools)
        coin = pools[index]
        try:
            value, receipt = http.gecko(f"/networks/solana/pools/{coin['primary_pool']}")
        except (R2SourceError, R2BudgetExceeded) as exc:
            state["stop_reason"] = str(exc)
            _save(path, state)
            return state
        pool = parse_pool(value["data"], datetime.fromisoformat(receipt["received_at"]))
        if coin["mint"] not in {pool.base_mint, pool.quote_mint}:
            raise ValueError("follow market mint/pool mismatch")
        price = pool.base_price_usd if pool.base_mint == coin["mint"] else pool.quote_price_usd
        state["market_snapshots"].append(
            {
                "mint": coin["mint"],
                "pool": coin["primary_pool"],
                "measured_at": None,
                "received_at": receipt["received_at"],
                "price_usd": str(price) if price is not None else None,
                "rolling_h24_volume_usd": str(pool.volume_h24_usd)
                if pool.volume_h24_usd is not None
                else None,
                "reserve_usd_snapshot": str(pool.reserve_usd)
                if pool.reserve_usd is not None
                else None,
                "historical_depth_usd": None,
                "source_hash": receipt["response_hash"],
                "attempt": receipt["attempt"],
                "volume_interval": "rolling_24h_not_additive",
            }
        )
        state["next_pool_index"] = index + 1
        _save(path, state)
    for wallet in [w["wallet"] for w in cohort["wallets"][:wallets_limit]]:
        try:
            signatures, receipt = http.rpc(
                "getSignaturesForAddress", [wallet, {"limit": 20, "commitment": "finalized"}]
            )
        except (R2SourceError, R2BudgetExceeded) as exc:
            state["stop_reason"] = str(exc)
            _save(path, state)
            return state
        known = state["wallets"].setdefault(wallet, {"seen": [], "last_checked_at": None})
        known.setdefault("coverage_started_at", receipt["received_at"])
        unseen = [s for s in signatures if s["signature"] not in known["seen"]]
        if (
            len(signatures) == 20
            and len(unseen) == 20
            and not any(
                g["wallet"] == wallet and g["reason"].startswith("page_full_all_unseen")
                for g in state["gaps"]
            )
        ):
            state["gaps"].append(
                {
                    "wallet": wallet,
                    "at": receipt["received_at"],
                    "reason": "page_full_all_unseen; older missed signatures possible",
                }
            )
        for item in reversed(unseen):
            if fetched >= transactions_limit:
                state["stop_reason"] = "transaction_cycle_limit; resume required"
                _save(path, state)
                return state
            sig = item["signature"]
            prior = _archived(http, sig)
            try:
                tx, tx_receipt = (
                    prior
                    if prior
                    else http.rpc(
                        "getTransaction",
                        [
                            sig,
                            {
                                "encoding": "jsonParsed",
                                "commitment": "finalized",
                                "maxSupportedTransactionVersion": 1,
                            },
                        ],
                    )
                )
            except (R2SourceError, R2BudgetExceeded) as exc:
                state["stop_reason"] = str(exc)
                _save(path, state)
                return state
            if tx is None:
                state["transactions"][sig] = {
                    "status": "unavailable",
                    "wallet": wallet,
                    "receipt": tx_receipt,
                }
            else:
                raw_path = root / "follow-raw" / f"{sig}.json"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                _save(raw_path, tx)
                decoded = decoder.decode(
                    tx, wallet, datetime.fromisoformat(tx_receipt["received_at"])
                )
                state["transactions"][sig] = {
                    "status": "fetched",
                    "wallet": wallet,
                    "kind": decoded.operation.kind
                    if decoded.operation.kind != "swap"
                    else "swap_balance_candidate",
                    "quality": decoded.operation.quality
                    if decoded.operation.kind != "swap"
                    else "requires_trade_reference",
                    "usd_value": None,
                    "receipt": tx_receipt,
                    "economic_at": decoded.operation.economic_at.isoformat(),
                    "fee_lamports": decoded.fee_lamports,
                    "decoder_version": decoded.parser_version,
                    "legs": [
                        {
                            "mint": leg.mint,
                            "delta_base": str(leg.delta_base),
                            "decimals": leg.decimals,
                        }
                        for leg in decoded.operation.legs
                    ],
                }
            known["seen"].append(sig)
            fetched += 1
            _save(path, state)
        known["last_checked_at"] = receipt["received_at"]
        _save(path, state)
    state["stop_reason"] = "cycle_complete"
    _save(path, state)
    return state


def refresh_follow_state(root: str | Path) -> dict:
    """Rebuild observable deltas from the archived RPC responses without data calls."""
    root = Path(root)
    path = root / "follow-checkpoint.json"
    state = json.loads(path.read_text())
    decoder = R2Decoder()
    for signature, item in state["transactions"].items():
        if item.get("status") != "fetched":
            continue
        raw = json.loads((root / "follow-raw" / f"{signature}.json").read_text())
        decoded = decoder.decode(
            raw, item["wallet"], datetime.fromisoformat(item["receipt"]["received_at"])
        )
        item["legs"] = [
            {"mint": leg.mint, "delta_base": str(leg.delta_base), "decimals": leg.decimals}
            for leg in decoded.operation.legs
        ]
    for wallet, info in state["wallets"].items():
        info.setdefault("coverage_started_at", state["started_at"])
    _save(path, state)
    return state
