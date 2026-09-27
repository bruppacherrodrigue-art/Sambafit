"""One coordinated, bounded R2 follow cycle. No background loop or orders."""

import json
import os
from collections.abc import Callable
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
    pages_limit: int = 2,
) -> dict:
    if (
        not 1 <= wallets_limit <= 40
        or not 0 <= pools_limit <= 12
        or not 0 <= transactions_limit <= 100
        or not 0 <= pages_limit <= 10
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
            "enrichment_queue": [],
            "market_snapshots": [],
            "gaps": [],
            "next_pool_index": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stop_reason": None,
        }
    )
    state["stop_reason"] = None
    state.setdefault("enrichment_queue", [])
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
    all_wallets = [w["wallet"] for w in cohort["wallets"]]
    if not all_wallets:
        state["stop_reason"] = "no_wallets"
        _save(path, state)
        return state
    start = state.get("next_wallet_index", 0) % len(all_wallets)
    selected = [
        all_wallets[(start + i) % len(all_wallets)]
        for i in range(min(wallets_limit, len(all_wallets)))
    ]
    state["next_wallet_index"] = (start + 1) % len(all_wallets)
    _save(path, state)
    scan_done = set()
    for page_number in range(pages_limit):
        for wallet in selected:
            if wallet in scan_done:
                continue
            known = state["wallets"].setdefault(wallet, {"seen": [], "last_checked_at": None})
            queue = known.setdefault("pending_signatures", [])
            known.setdefault("coverage_started_at", state["started_at"])
            cursor = known.get("scan_cursor")
            options = {"limit": 20, "commitment": "finalized"}
            if cursor:
                options["before"] = cursor
            try:
                signatures, receipt = http.rpc("getSignaturesForAddress", [wallet, options])
            except (R2SourceError, R2BudgetExceeded) as exc:
                state["stop_reason"] = str(exc)
                _save(path, state)
                return state
            signatures = signatures or []
            if not cursor and signatures:
                known["scan_newest"] = signatures[0]["signature"]
            anchor = known.get("anchor_signature") or (known["seen"][-1] if known["seen"] else None)
            discovered = []
            reached_anchor = False
            for item in signatures:
                sig = item["signature"]
                if sig == anchor:
                    reached_anchor = True
                    break
                if sig not in known["seen"] and sig not in queue:
                    discovered.append(sig)
            known["pending_signatures"] = list(reversed(discovered)) + queue
            known["last_checked_at"] = receipt["received_at"]
            if reached_anchor or len(signatures) < 20:
                known["scan_cursor"] = None
                if known.get("scan_newest"):
                    known["anchor_signature"] = known.pop("scan_newest")
                scan_done.add(wallet)
            else:
                known["scan_cursor"] = signatures[-1]["signature"]
                if page_number == pages_limit - 1:
                    state["gaps"].append(
                        {
                            "wallet": wallet,
                            "at": receipt["received_at"],
                            "reason": "page_limit_reached; older signatures queued for next cycle",
                            "resume_before": known["scan_cursor"],
                        }
                    )
            _save(path, state)
    attempted_this_cycle = set()
    while fetched < transactions_limit:
        progressed = False
        for wallet in selected:
            known = state["wallets"][wallet]
            sig = next(
                (
                    sig
                    for sig in reversed(known["pending_signatures"])
                    if sig not in attempted_this_cycle
                ),
                None,
            )
            if sig is None or fetched >= transactions_limit:
                continue
            attempted_this_cycle.add(sig)
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
                    "decoded_at": datetime.now(timezone.utc).isoformat(),
                    "retryable": True,
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
                    "kind": decoded.operation.kind,
                    "quality": decoded.operation.quality,
                    "usd_value": None,
                    "valuation_status": "missing_point_in_time_price",
                    "receipt": tx_receipt,
                    "economic_at": decoded.operation.economic_at.isoformat(),
                    "fee_lamports": decoded.fee_lamports,
                    "decoder_version": decoded.parser_version,
                    "operation_id": decoded.operation.id,
                    "legs": [
                        {
                            "mint": leg.mint,
                            "delta_base": str(leg.delta_base),
                            "decimals": leg.decimals,
                        }
                        for leg in decoded.operation.legs
                    ],
                }
                if decoded.operation.kind == "unknown" or decoded.operation.quality != "complete":
                    if not any(item["signature"] == sig for item in state["enrichment_queue"]):
                        state["enrichment_queue"].append(
                            {
                                "signature": sig,
                                "wallet": wallet,
                                "reason": decoded.operation.quality,
                                "source_attempt": tx_receipt["attempt"],
                                "source_hash": tx_receipt["response_hash"],
                                "decoder_version": decoded.parser_version,
                                "status": "awaiting_supported_route_or_authorized_reference",
                            }
                        )
                known["pending_signatures"].remove(sig)
                if sig not in known["seen"]:
                    known["seen"].append(sig)
            fetched += 1
            progressed = True
            _save(path, state)
        if not progressed:
            break
    state["stop_reason"] = (
        "transaction_cycle_limit; resume required"
        if fetched >= transactions_limit
        and any(state["wallets"][w]["pending_signatures"] for w in selected)
        else "cycle_complete"
    )
    _save(path, state)
    return state


def refresh_follow_state(
    root: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    decoder: R2Decoder | None = None,
) -> dict:
    """Rebuild observable deltas from the archived RPC responses without data calls."""
    root = Path(root)
    path = root / "follow-checkpoint.json"
    state = json.loads(path.read_text())
    state.setdefault("enrichment_queue", [])
    decoder = decoder or R2Decoder()
    clock = now or (lambda: datetime.now(timezone.utc))
    for signature, item in state["transactions"].items():
        if item.get("status") != "fetched":
            continue
        raw = json.loads((root / "follow-raw" / f"{signature}.json").read_text())
        decoded = decoder.decode(
            raw, item["wallet"], datetime.fromisoformat(item["receipt"]["received_at"])
        )
        revised_legs = [
            {"mint": leg.mint, "delta_base": str(leg.delta_base), "decimals": leg.decimals}
            for leg in decoded.operation.legs
        ]
        previous = {
            "kind": item.get("kind"),
            "quality": item.get("quality"),
            "legs": item.get("legs", []),
            "decoder_version": item.get("decoder_version"),
        }
        updated = {
            "kind": decoded.operation.kind,
            "quality": decoded.operation.quality,
            "legs": revised_legs,
            "decoder_version": decoded.parser_version,
        }
        if previous != updated:
            decoded_at = clock()
            if decoded_at.tzinfo is None:
                raise ValueError("timezone-aware decode clock required")
            receipt_at = datetime.fromisoformat(item["receipt"]["received_at"])
            if decoded_at < receipt_at:
                raise ValueError("decode cannot precede raw receipt")
            revisions = item.setdefault(
                "decode_revisions",
                [
                    {
                        **previous,
                        "known_at": item.get("decoded_at"),
                        "knowledge_time_quality": "observed"
                        if item.get("decoded_at")
                        else "legacy_unknown",
                    }
                ],
            )
            revisions.append(
                {
                    **updated,
                    "known_at": decoded_at.isoformat(),
                    "knowledge_time_quality": "observed",
                }
            )
            item.update(updated)
            item["decoded_at"] = decoded_at.isoformat()
            item["effective_available_at"] = decoded_at.isoformat()
        elif "effective_available_at" not in item:
            # Rechecking a legacy row proves the parse only now. Keep the old
            # undocumented timestamp as unknown, and issue a new revision.
            if not item.get("decoded_at"):
                decoded_at = clock()
                receipt_at = datetime.fromisoformat(item["receipt"]["received_at"])
                if decoded_at.tzinfo is None or decoded_at < receipt_at:
                    raise ValueError("decode clock must follow receipt")
                item["decode_revisions"] = [
                    {**previous, "known_at": None, "knowledge_time_quality": "legacy_unknown"},
                    {
                        **updated,
                        "known_at": decoded_at.isoformat(),
                        "knowledge_time_quality": "observed_reverification",
                    },
                ]
                item["decoded_at"] = decoded_at.isoformat()
                item["effective_available_at"] = decoded_at.isoformat()
            else:
                item["effective_available_at"] = item["decoded_at"]
        if decoded.operation.kind != "unknown" and decoded.operation.quality == "complete":
            state["enrichment_queue"] = [
                row for row in state["enrichment_queue"] if row["signature"] != signature
            ]
        elif not any(row["signature"] == signature for row in state["enrichment_queue"]):
            state["enrichment_queue"].append(
                {
                    "signature": signature,
                    "wallet": item["wallet"],
                    "reason": decoded.operation.quality,
                    "source_attempt": item["receipt"]["attempt"],
                    "source_hash": item["receipt"]["response_hash"],
                    "decoder_version": decoded.parser_version,
                    "status": "awaiting_supported_route_or_authorized_reference",
                }
            )
    for wallet, info in state["wallets"].items():
        info.setdefault("coverage_started_at", state["started_at"])
    _save(path, state)
    return state
