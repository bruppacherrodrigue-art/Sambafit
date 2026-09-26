"""Offline import and independent field audit for a frozen public pilot corpus."""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .market import parse_candles
from .solana import PARSER_VERSION, SolanaDecoder

METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUP_SOL_POOL = "C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg"
JUP_USDC_POOL = "Et6HnPjetV8AzmxNAfzKJ6ax5VM82ZB7phY465Ns5iZW"


def _receipt(path: Path) -> datetime:
    # The collector wrote the file immediately after response; a copy retains mtime.
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def verify_source_receipts(root: str | Path) -> int:
    root = Path(root)
    receipts = json.loads((root / "source-receipts.json").read_text())
    for filename, proof in receipts.items():
        payload = json.loads((root / filename).read_text())
        raw = payload.get("response", payload)
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
        if sha256(canonical.encode()).hexdigest() != proof["raw_sha256"]:
            raise ValueError(f"source response hash mismatch {filename}")
    return len(receipts)


def load_verified(root: str | Path) -> list[tuple[dict, dict, object]]:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    decoder = SolanaDecoder({METEORA_DLMM})
    result = []
    seen = set()
    for row in manifest["records"]:
        signature = row["signature"]
        if signature in seen:
            raise ValueError(f"duplicate signature {signature}")
        seen.add(signature)
        if row["status"] != "fetched":
            continue
        path = root / "raw" / f"{signature}.json"
        tx = json.loads(path.read_text())
        actual = sha256(
            json.dumps(tx, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        if actual != row["source_hash"]:
            raise ValueError(f"raw hash mismatch {signature}")
        if tx["transaction"]["signatures"][0] != signature:
            raise ValueError(f"raw signature mismatch {signature}")
        actor = row.get("reported_actor")
        if not actor:
            continue  # Preserve raw in corpus; no unsupported actor attribution.
        # Frozen corpus reuses the actual pilot decode time; a fresh import cannot
        # manufacture an earlier bot decision or shift a historical replay.
        available = (
            datetime.fromisoformat(row["decoded_at"])
            if row.get("decoded_at")
            else datetime.now(timezone.utc)
        )
        decoded = decoder.decode(tx, actor, available)
        result.append((row, tx, decoded))
    return result


def independent_balance_audit(row: dict, tx: dict, decoded) -> dict:
    """Recompute owner deltas directly from RPC balance arrays, without decoder helpers."""
    owner = row["reported_actor"]
    keys = tx["transaction"]["message"]["accountKeys"]
    signers = [key["pubkey"] for key in keys if isinstance(key, dict) and key.get("signer")]
    payer = keys[0]["pubkey"] if keys and isinstance(keys[0], dict) else None
    delta = Counter()
    decimals = {}
    for side, multiplier in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for item in tx["meta"].get(side) or []:
            if item.get("owner") == owner:
                mint = item["mint"]
                amount = item["uiTokenAmount"]
                delta[mint] += multiplier * int(amount["amount"])
                decimals[mint] = int(amount["decimals"])
    observed = sorted((mint, amount, decimals[mint]) for mint, amount in delta.items() if amount)
    predicted = sorted((leg.mint, leg.delta_base, leg.decimals) for leg in decoded.operation.legs)
    instructions = list(tx["transaction"]["message"].get("instructions") or [])
    for group in tx["meta"].get("innerInstructions") or []:
        instructions.extend(group.get("instructions") or [])
    programs = sorted({item.get("programId") for item in instructions if item.get("programId")})
    fee = int(tx["meta"].get("fee") or 0)
    return {
        "signature": row["signature"],
        "slot": tx["slot"],
        "version": tx.get("version"),
        "economic_at": datetime.fromtimestamp(tx["blockTime"], timezone.utc).isoformat()
        if tx.get("blockTime") is not None
        else None,
        "reported_actor": owner,
        "payer": payer,
        "signers": signers,
        "actor_signed": owner in signers,
        "fee_lamports": fee,
        "programs": programs,
        "raw_owner_deltas": observed,
        "decoder_legs": predicted,
        "balances_match": observed == predicted,
        "decoded_kind": decoded.operation.kind,
        "quality": decoded.operation.quality,
        "reference_kind": row.get("reference_kind"),
    }


def summarize_corpus(root: str | Path) -> dict:
    verify_source_receipts(root)
    entries = load_verified(root)
    audits = [independent_balance_audit(row, tx, decoded) for row, tx, decoded in entries]
    kinds = Counter((item["decoded_kind"], item["quality"]) for item in audits)
    swaps = [
        item for item in audits if item["decoded_kind"] == "swap" and item["quality"] == "complete"
    ]
    wallets = sorted({item["reported_actor"] for item in swaps})
    return {
        "transactions_fetched": len(entries),
        "provider_trade_references": len(entries),
        "decoded_swaps": len(swaps),
        "wallets_with_complete_swaps": len(wallets),
        "wallet_addresses": wallets,
        "classification_counts": {
            f"{kind}:{quality}": n for (kind, quality), n in sorted(kinds.items())
        },
        "balance_mismatches": [item["signature"] for item in audits if not item["balances_match"]],
        "audits": audits,
    }


def verify_manifest(root: str | Path) -> dict:
    """Attach reproducible program/role evidence without changing raw response hashes."""
    root = Path(root)
    verify_source_receipts(root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # A decode performed during this audit becomes available now, not at block time.
    stamped = False
    for row in manifest["records"]:
        if row["status"] == "fetched" and row.get("reported_actor") and not row.get("decoded_at"):
            row["decoded_at"] = datetime.now(timezone.utc).isoformat()
            stamped = True
    if stamped:
        temp = manifest_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        os.replace(temp, manifest_path)
    summary = summarize_corpus(root)
    checks = {item["signature"]: item for item in summary["audits"]}
    for row in manifest["records"]:
        item = checks.get(row["signature"])
        if item is None:
            continue
        row.update(
            {
                "decoder_version": PARSER_VERSION,
                "decoded_kind": item["decoded_kind"],
                "decode_quality": item["quality"],
                "programs": item["programs"],
                "payer": item["payer"],
                "signers": item["signers"],
                "actor_signed": item["actor_signed"],
                "owner_balance_check": item["balances_match"],
                "raw_received_at": row.get("raw_received_at")
                or _receipt(root / "raw" / f"{row['signature']}.json").isoformat(),
            }
        )
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temp, manifest_path)
    audit_path = root / "verification.json"
    temp = audit_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    os.replace(temp, audit_path)
    return {key: value for key, value in summary.items() if key != "audits"}


def import_corpus(store, root: str | Path) -> dict:
    root = Path(root)
    verify_source_receipts(root)
    protocol_path = root / "protocol.json"
    protocol = json.loads(protocol_path.read_text()) if protocol_path.exists() else {}
    selected_pools = protocol.get("selected_pools", {})
    sol_pool = selected_pools.get("jup_sol", JUP_SOL_POOL)
    usdc_pool = selected_pools.get("jup_usdc", JUP_USDC_POOL)
    known_at = protocol.get("started_at", "2026-09-26T06:29:58Z")
    store.migrate()
    entries = load_verified(root)
    store.import_watchlist(
        [
            {
                "network": "solana",
                "mint": mint,
                "symbol": symbol,
                "decimals": decimals,
                "eligible_from": known_at,
                "metadata": {"scope": "technical_pilot_only", "source": source},
            }
            for mint, symbol, decimals, source in (
                (JUP, "JUP", 6, "Jupiter Research mint record"),
                (WSOL, "wSOL", 9, "Solana native mint record"),
                (USDC, "USDC", 6, "Circle native Solana mint record"),
            )
        ],
        known_at,
    )
    summary = summarize_corpus(root)
    store.import_wallets(
        [
            {
                "address": address,
                "category": "unknown",
                "category_reason": "unattributed signer with a complete swap in bounded technical sample",
            }
            for address in summary["wallet_addresses"]
        ]
    )
    added_raw = 0
    for row, tx, decoded in entries:
        raw_path = root / "raw" / f"{row['signature']}.json"
        added_raw += int(
            store.add_raw(
                row["signature"],
                row["reported_actor"],
                tx,
                "solana_finalized_rpc+gecko_trade_reference",
                row["parser_version"],
                first_seen_at=datetime.fromisoformat(row["raw_received_at"])
                if row.get("raw_received_at")
                else _receipt(raw_path),
                dataset="REAL",
            )
        )
        store.add_operation(
            row["signature"],
            row["reported_actor"],
            decoded.operation,
            decoded.fee_lamports,
            PARSER_VERSION,
            "REAL",
            decoded_at=decoded.operation.available_at,
        )
    bars = 0
    for filename, pool, mint in (
        ("jup-sol-ohlcv.json", sol_pool, JUP),
        ("sol-usd-ohlcv.json", sol_pool, WSOL),
        ("usdc-usd-ohlcv.json", usdc_pool, USDC),
    ):
        path = root / filename
        payload = json.loads(path.read_text())
        if "response" in payload:
            received = datetime.fromisoformat(payload["received_at"])
            payload = payload["response"]
        else:
            received = _receipt(path)
        for candle in parse_candles(payload, pool, mint, received):
            bars += int(
                store.add_market_bar(
                    mint,
                    candle.close_at,
                    candle.received_at,
                    candle.close_usd,
                    candle.volume_usd,
                    None,
                    f"geckoterminal_ohlcv:{pool}",
                    "REAL",
                    "20230203",
                )
            )
    if added_raw:
        for reason in (
            "pilot covers only 30 recent references from each of two JUP pools; wallet histories incomplete",
            "partial balance decoding for composite routes, native SOL and closed token accounts",
            "historical executable liquidity and depth unavailable; spot reserve not backfilled",
        ):
            store.add_coverage_gap(None, reason)
    return {
        "raw_inserted": added_raw,
        "transactions": len(entries),
        "market_bars_inserted": bars,
        "decoder_version": PARSER_VERSION,
        "historical_liquidity": "unavailable",
    }
