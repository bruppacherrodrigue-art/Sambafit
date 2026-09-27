"""Amount-first preselection and strict on-chain cohort audit for the R3 sample."""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from .market import TradeRef, parse_trades
from .r2_decode import R2Decoder
from .r2_sequences import SequenceStore
from .r3_registry import ResearchRegistry
from .real_corpus import independent_balance_audit


def select_references(
    r2_root: str | Path,
    registry: ResearchRegistry,
    *,
    min_usd: Decimal = Decimal("500"),
    max_refs: int = 24,
) -> dict:
    if min_usd <= 0 or not 1 <= max_refs <= 100:
        raise ValueError("bounded positive preselection required")
    root = Path(r2_root)
    eligible = registry.eligible_mints(datetime.fromisoformat(registry.known_at))
    r2_universe = json.loads((root.parent.parent / "config" / "r2-candidates.json").read_text())
    pools = {row["primary_pool"]: row for row in r2_universe["records"] if row["mint"] in eligible}
    trades_by_pool = {}
    coverage = {}
    for path in sorted((root / "source").glob("attempt-*.json")):
        archive = json.loads(path.read_text())
        request = archive.get("request", "")
        if not request.startswith("GET /networks/solana/pools/") or not request.endswith("/trades"):
            continue
        pool = request.split("/pools/")[1].split("/trades")[0]
        if pool not in pools or archive.get("http_status") != 200:
            continue
        trades = parse_trades(json.loads(archive["body"]), pool)
        if not trades:
            continue
        trades_by_pool[pool] = (trades, archive)
        coverage[pool] = {
            "mint": pools[pool]["mint"],
            "symbol": pools[pool]["symbol"],
            "count": len(trades),
            "first_at": min(trade.block_at for trade in trades).isoformat(),
            "last_at": max(trade.block_at for trade in trades).isoformat(),
            "source_attempt": archive["attempt"],
            "response_hash": archive["response_hash"],
        }
    if not trades_by_pool:
        raise ValueError("no archived eligible pool trades")
    common_start = max(
        min(trade.block_at for trade in trades) for trades, _ in trades_by_pool.values()
    )
    common_end = min(
        max(trade.block_at for trade in trades) for trades, _ in trades_by_pool.values()
    )
    if common_end < common_start:
        raise ValueError("no common sampled window")
    selected = {}
    for pool, (trades, archive) in trades_by_pool.items():
        for trade in trades:
            if (
                not common_start <= trade.block_at <= common_end
                or trade.volume_usd is None
                or trade.volume_usd < min_usd
            ):
                continue
            row = {
                "signature": trade.signature,
                "slot": trade.slot,
                "block_at": trade.block_at.isoformat(),
                "pool": pool,
                "pool_mint": pools[pool]["mint"],
                "provider_actor": trade.reported_actor,
                "provider_kind": trade.kind,
                "provider_volume_usd": str(trade.volume_usd),
                "from_mint": trade.from_mint,
                "to_mint": trade.to_mint,
                "from_amount": str(trade.from_amount),
                "to_amount": str(trade.to_amount),
                "source_attempt": archive["attempt"],
                "source_hash": archive["response_hash"],
                "attribution_status": "unverified",
            }
            existing = selected.get(trade.signature)
            if existing is None or trade.volume_usd > Decimal(existing["provider_volume_usd"]):
                selected[trade.signature] = row
    ranked = sorted(
        selected.values(), key=lambda row: (-Decimal(row["provider_volume_usd"]), row["signature"])
    )
    return {
        "scope": "sample_preselection_not_qualified_wallets",
        "registry_version": registry.version,
        "threshold_usd": str(min_usd),
        "max_references": max_refs,
        "common_window": {"start": common_start.isoformat(), "end": common_end.isoformat()},
        "pool_coverage": coverage,
        "eligible_references_above_threshold": len(ranked),
        "references": ranked[:max_refs],
        "selection_bias": "retrospective_on_r2_sample",
    }


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def _reference(row: dict) -> TradeRef:
    return TradeRef(
        row["signature"],
        row["slot"],
        datetime.fromisoformat(row["block_at"]),
        row["provider_actor"],
        row["provider_kind"],
        row["from_mint"],
        row["to_mint"],
        Decimal(row["from_amount"]),
        Decimal(row["to_amount"]),
        Decimal(row["provider_volume_usd"]),
        row["pool"],
    )


def build_manifest(root: str | Path) -> dict:
    """Deterministic inventory of archived real responses and their decode status."""
    root = Path(root)
    selected = json.loads((root / "preselection.json").read_text())["references"]
    follow_path = root / "follow-checkpoint.json"
    followed = json.loads(follow_path.read_text()) if follow_path.exists() else {"transactions": {}}
    budget = json.loads((root / "budget.json").read_text())
    rows = []
    for selection in selected:
        signature = selection["signature"]
        rows.append((signature, selection, "preselection", root / "raw" / f"{signature}.json"))
    for signature, selection in followed["transactions"].items():
        if signature not in {row[0] for row in rows}:
            rows.append(
                (signature, selection, "prospective", root / "follow-raw" / f"{signature}.json")
            )
    transactions = []
    for signature, item, phase, path in sorted(rows):
        raw = json.loads(path.read_text()) if path.exists() else None
        instructions = [] if raw is None else raw["transaction"]["message"].get("instructions", [])
        if raw is not None:
            instructions += [
                instruction
                for group in raw.get("meta", {}).get("innerInstructions", []) or []
                for instruction in group.get("instructions", [])
            ]
        transactions.append(
            {
                "signature": signature,
                "phase": phase,
                "slot": item.get("slot", raw.get("slot") if raw else None),
                "block_at": item.get("block_at", item.get("economic_at")),
                "received_at": item.get(
                    "raw_received_at", item.get("receipt", {}).get("received_at")
                ),
                "reference_source_hash": item.get("source_hash"),
                "rpc_response_hash": item.get("receipt", {}).get(
                    "response_hash",
                    next(
                        (
                            attempt["response_hash"]
                            for attempt in budget["attempts"]
                            if attempt["request"] == f"getTransaction:{signature}"
                            and attempt["status"] == "http_200"
                        ),
                        None,
                    ),
                ),
                "raw_file": str(path.relative_to(root)) if path.exists() else None,
                "raw_file_sha256": sha256(path.read_bytes()).hexdigest() if path.exists() else None,
                "programs": sorted(
                    {
                        instruction.get("programId", "")
                        for instruction in instructions
                        if instruction.get("programId")
                    }
                ),
                "decoder_version": item.get("decoder_version"),
                "decode_status": item.get("attribution_status", item.get("quality", "pending")),
                "operation_id": item.get("operation_id"),
            }
        )
    result = {
        "dataset": "REAL",
        "mode": "R3_CORPUS_MANIFEST",
        "attempts": budget["attempts"],
        "calls_used": budget["calls_used"],
        "transactions": transactions,
        "selected_count": len(selected),
        "followed_count": len(followed["transactions"]),
    }
    _write(root / "manifest.json", result)
    return result


def audit_selected(
    r2_root: str | Path,
    r3_root: str | Path,
    http,
    *,
    max_new_calls: int = 24,
) -> dict:
    """Persist each proof before advancing; RPC null remains retryable."""
    r2_root, r3_root = Path(r2_root), Path(r3_root)
    path = r3_root / "preselection.json"
    selected = json.loads(path.read_text())
    r2_rows = {
        row["signature"]: row
        for row in json.loads((r2_root / "tx-selection.json").read_text())["records"]
    }
    calls = 0
    decoder = R2Decoder()
    for row in selected["references"]:
        if row["attribution_status"] in {"verified_swap", "partial", "unsupported", "failed"}:
            continue
        signature = row["signature"]
        raw_path = r3_root / "raw" / f"{signature}.json"
        r2_path = r2_root / "raw" / f"{signature}.json"
        if raw_path.exists():
            tx = json.loads(raw_path.read_text())
            received_at = row["raw_received_at"]
            raw_source = row["raw_source"]
        elif r2_path.exists():
            tx = json.loads(r2_path.read_text())
            old = r2_rows[signature]
            received_at = old["raw_received_at"]
            raw_source = "r2_archived_rpc"
            _write(raw_path, tx)
        else:
            if calls >= max_new_calls:
                break
            from .r2_budget import R2BudgetExceeded
            from .r2_sources import R2SourceError

            try:
                tx, receipt = http.rpc(
                    "getTransaction",
                    [
                        signature,
                        {
                            "encoding": "jsonParsed",
                            "commitment": "finalized",
                            "maxSupportedTransactionVersion": 1,
                        },
                    ],
                )
            except (R2SourceError, R2BudgetExceeded) as exc:
                row["attribution_status"] = "retryable_error"
                row["error"] = str(exc)
                _write(path, selected)
                break
            calls += 1
            if tx is None:
                row["attribution_status"] = "retryable_null"
                row["last_attempt"] = receipt["attempt"]
                _write(path, selected)
                continue
            received_at = receipt["received_at"]
            raw_source = "r3_rpc"
            row["raw_attempt"] = receipt["attempt"]
            row["raw_response_hash"] = receipt["response_hash"]
            _write(raw_path, tx)
        if (tx.get("transaction") or {}).get("signatures", [None])[0] != signature:
            row["attribution_status"] = "retryable_error"
            row["error"] = "RPC signature mismatch"
            _write(path, selected)
            break
        decoded = decoder.decode(
            tx, row["provider_actor"], datetime.fromisoformat(received_at), _reference(row)
        )
        operation = decoded.operation
        row.update(
            attribution_status=(
                "verified_swap"
                if operation.kind == "swap" and operation.quality == "complete"
                else "failed"
                if operation.kind == "failed"
                else "unsupported"
                if operation.quality == "unsupported_program"
                else "partial"
            ),
            kind=operation.kind,
            quality=operation.quality,
            decoder_version=decoded.parser_version,
            raw_received_at=received_at,
            raw_source=raw_source,
            fee_lamports=decoded.fee_lamports,
            owner_wallet=operation.wallet if operation.quality == "complete" else None,
            legs=[
                {"mint": leg.mint, "delta_base": str(leg.delta_base), "decimals": leg.decimals}
                for leg in operation.legs
            ],
        )
        _write(path, selected)
    selected["new_rpc_calls_last_run"] = calls
    _write(path, selected)
    return selected


def rank_verified(
    r3_root: str | Path,
    registry: ResearchRegistry,
    *,
    min_rotation_usd: Decimal = Decimal("1000"),
    max_wallets: int = 10,
) -> dict:
    """Only strict owner/signer swaps enter research rankings."""
    if min_rotation_usd <= 0 or not 1 <= max_wallets <= 40:
        raise ValueError("bounded cohort parameters required")
    root = Path(r3_root)
    selected = json.loads((root / "preselection.json").read_text())
    eligible = registry.eligible_mints(datetime.fromisoformat(registry.known_at))
    reserves = {row["mint"] for row in registry.payload["records"] if row["role"] == "reserve"}
    events = []
    wallets = defaultdict(
        lambda: {
            "signatures": [],
            "gross_buy_usd": Decimal(0),
            "gross_sell_usd": Decimal(0),
            "per_coin": defaultdict(lambda: {"buy_usd": Decimal(0), "sell_usd": Decimal(0)}),
        }
    )
    for row in selected["references"]:
        if row["attribution_status"] != "verified_swap":
            continue
        coin = row["pool_mint"]
        legs = row["legs"]
        coin_leg = next((leg for leg in legs if leg["mint"] == coin), None)
        reserve_leg = next((leg for leg in legs if leg["mint"] in reserves), None)
        if coin_leg is None or reserve_leg is None or len(legs) != 2:
            continue
        wallet = row["owner_wallet"]
        amount = Decimal(row["provider_volume_usd"])
        direction = "buy" if int(coin_leg["delta_base"]) > 0 else "sell"
        item = wallets[wallet]
        item["signatures"].append(row["signature"])
        item[f"gross_{direction}_usd"] += amount
        item["per_coin"][coin][f"{direction}_usd"] += amount
        events.append(
            {
                "signature": row["signature"],
                "wallet": wallet,
                "coin_mint": coin,
                "direction": direction,
                "reserve_mint": reserve_leg["mint"],
                "reserve_quantity_base": str(abs(int(reserve_leg["delta_base"]))),
                "reserve_decimals": reserve_leg["decimals"],
                "amount_usd": str(amount),
                "economic_at": row["block_at"],
                "available_at": row["raw_received_at"],
                "valuation": "geckoterminal_trade_proxy_at_economic_time",
            }
        )
    with SequenceStore(root / "sequences.sqlite", eligible_mints=eligible) as store:
        store.add(events)
        sequences = store.snapshot()
    attributed = defaultdict(lambda: Decimal(0))
    quantities = defaultdict(lambda: defaultdict(int))
    for row in sequences["allocations"]:
        if row["amount_usd"] is not None:
            attributed[row["wallet"]] += Decimal(row["amount_usd"])
        if row["reserve_quantity_base"] is not None:
            quantities[row["wallet"]][row["reserve_mint"]] += int(row["reserve_quantity_base"])
    ranked = []
    for wallet, item in wallets.items():
        gross = item["gross_buy_usd"] + item["gross_sell_usd"]
        circular = sum(
            (
                min(measures["buy_usd"], measures["sell_usd"]) * 2
                for measures in item["per_coin"].values()
            ),
            Decimal(0),
        )
        passes_amount = attributed[wallet] >= min_rotation_usd
        ranked.append(
            {
                "wallet": wallet,
                "provenance": "onchain_unattributed",
                "sample_signatures": sorted(item["signatures"]),
                "strict_swaps": len(item["signatures"]),
                "gross_buy_usd": str(item["gross_buy_usd"]),
                "gross_sell_usd": str(item["gross_sell_usd"]),
                "attributed_between_memecoins_usd": str(attributed[wallet]),
                "attributed_reserve_base_by_mint": dict(quantities[wallet]),
                "circular_gross_fraction": str(circular / gross) if gross else None,
                "per_coin": {
                    coin: {kind: str(value) for kind, value in measures.items()}
                    for coin, measures in item["per_coin"].items()
                },
                "passes_amount_screen": passes_amount,
                "qualified_large_reallocator": False,
                "qualification_status": (
                    "amount_candidate_directionality_and_persistence_unverified"
                    if passes_amount
                    else "below_amount_screen_in_sample"
                ),
                "holding_duration": None,
                "opening_position_unknown": True,
                "category": "unknown",
                "category_reason": (
                    "high_frequency_alone_does_not_prove_arbitrage"
                    if len(item["signatures"]) >= 10
                    else "insufficient_behavioral_coverage"
                ),
                "uncertainty": "sampled references and only strict decoded swaps; no total wealth",
            }
        )
    ranked.sort(
        key=lambda row: (
            -Decimal(row["attributed_between_memecoins_usd"]),
            -(Decimal(row["gross_buy_usd"]) + Decimal(row["gross_sell_usd"])),
            row["wallet"],
        )
    )
    prior_path = root / "cohort.json"
    prior_known_at = (
        json.loads(prior_path.read_text()).get("cohort_known_at") if prior_path.exists() else None
    )
    result = {
        "scope": "wallet_candidates_in_sample_not_all_solana",
        "selection_bias": "retrospective_on_r2_sample",
        "cohort_known_at": prior_known_at or datetime.now(timezone.utc).isoformat(),
        "registry_version": registry.version,
        "threshold_usd": str(min_rotation_usd),
        "max_wallets": max_wallets,
        "sample_window": selected["common_window"],
        "strict_swap_count": len(events),
        "amount_screen_wallets": sum(row["passes_amount_screen"] for row in ranked),
        "qualified_wallets": 0,
        "wallets": ranked[:max_wallets],
        "sequences": sequences,
    }
    _write(root / "cohort.json", result)
    return result


def verify_selected(r3_root: str | Path) -> dict:
    """Independent recomputation from raw owner balances and instruction programs."""
    root = Path(r3_root)
    selected = json.loads((root / "preselection.json").read_text())
    decoder = R2Decoder()
    audits = []
    balance_mismatches = []
    reference_mismatches = []
    for row in selected["references"]:
        if row["attribution_status"] != "verified_swap":
            continue
        tx = json.loads((root / "raw" / f"{row['signature']}.json").read_text())
        if tx["transaction"]["signatures"][0] != row["signature"]:
            raise ValueError("archived signature mismatch")
        decoded = decoder.decode(
            tx,
            row["provider_actor"],
            datetime.fromisoformat(row["raw_received_at"]),
            _reference(row),
        )
        audit = independent_balance_audit(
            {"signature": row["signature"], "reported_actor": row["provider_actor"]},
            tx,
            decoded,
        )
        row_legs = sorted(
            (leg["mint"], int(leg["delta_base"]), int(leg["decimals"])) for leg in row["legs"]
        )
        if not audit["balances_match"] or row_legs != audit["raw_owner_deltas"]:
            balance_mismatches.append(row["signature"])
        amounts = {
            mint: Decimal(abs(delta)) / (Decimal(10) ** decimals)
            for mint, delta, decimals in audit["raw_owner_deltas"]
        }
        reference_ok = set(amounts) == {row["from_mint"], row["to_mint"]} and all(
            abs(amounts[mint] - Decimal(row[key])) / Decimal(row[key]) <= Decimal("0.01")
            for mint, key in ((row["from_mint"], "from_amount"), (row["to_mint"], "to_amount"))
        )
        if not reference_ok:
            reference_mismatches.append(row["signature"])
        audit["reference_amounts_match"] = reference_ok
        audit["raw_sha256"] = sha256(
            json.dumps(tx, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        audit["raw_source"] = row["raw_source"]
        audit["source_attempt"] = row["source_attempt"]
        audits.append(audit)
    result = {
        "verified_swaps": len(audits),
        "balance_mismatches": balance_mismatches,
        "reference_mismatches": reference_mismatches,
        "audits": audits,
    }
    _write(root / "verification.json", result)
    return result
