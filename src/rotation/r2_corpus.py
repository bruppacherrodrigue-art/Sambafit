"""Offline verified R2 corpus and exploratory on-chain cohort."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from .market import TradeRef, parse_trades
from .r2_decode import R2_PARSER_VERSION, R2Decoder
from .real_corpus import independent_balance_audit


def _sha(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_archives(root: str | Path) -> dict:
    root = Path(root)
    budget = json.loads((root / "budget.json").read_text())
    archives = sorted((root / "source").glob("attempt-*.json"))
    if len(archives) != budget["calls_used"] or len(budget["attempts"]) != budget["calls_used"]:
        raise ValueError("R2 attempt/archive count mismatch")
    for number, path in enumerate(archives, 1):
        record = json.loads(path.read_text())
        if record["attempt"] != number or budget["attempts"][number - 1]["number"] != number:
            raise ValueError("R2 attempt order mismatch")
        expected = record.get("response_hash")
        if expected and sha256(record["body"].encode()).hexdigest() != expected:
            raise ValueError(f"R2 source hash mismatch: {number}")
        if expected != budget["attempts"][number - 1].get("response_hash"):
            raise ValueError(f"R2 budget receipt mismatch: {number}")
    return {
        "attempts": len(archives),
        "active_seconds": budget["active_seconds"],
        "errors": [a for a in budget["attempts"] if a["status"] != "http_200"],
    }


def load_references(root: Path) -> dict[str, TradeRef]:
    result = {}
    for number in range(37, 48):
        archive = json.loads((root / "source" / f"attempt-{number:04}.json").read_text())
        if archive["http_status"] != 200:
            continue
        pool = archive["request"].split("/pools/")[1].split("/trades")[0]
        for trade in parse_trades(json.loads(archive["body"]), pool):
            result.setdefault(trade.signature, trade)
    return result


def verify_corpus(root: str | Path) -> dict:
    root = Path(root)
    verify_archives(root)
    manifest_path = root / "tx-selection.json"
    manifest = json.loads(manifest_path.read_text())
    refs = load_references(root)
    decoder = R2Decoder()
    count = Counter()
    audits = []
    cohort = defaultdict(
        lambda: {
            "signatures": [],
            "per_coin": defaultdict(
                lambda: {"buys_usd": Decimal(0), "sells_usd": Decimal(0), "swaps": 0}
            ),
            "observed_usd": Decimal(0),
            "rotation_usd": Decimal(0),
            "first_at": None,
            "last_at": None,
        }
    )
    events = []
    seen = set()
    for row in manifest["records"]:
        sig = row["signature"]
        if sig in seen:
            raise ValueError("duplicate selected signature")
        seen.add(sig)
        if row["status"] != "fetched":
            count[row["status"]] += 1
            continue
        raw = json.loads((root / "raw" / f"{sig}.json").read_text())
        if _sha(raw) != row["raw_hash"] or raw["transaction"]["signatures"][0] != sig:
            raise ValueError(f"raw mismatch: {sig}")
        ref = refs.get(sig)
        if ref is None or ref.pool != row["pool"] or ref.reported_actor != row["reported_actor"]:
            raise ValueError(f"provider reference mismatch: {sig}")
        receipt = datetime.fromisoformat(row["raw_received_at"])
        decoded = decoder.decode(raw, row["reported_actor"], receipt, ref)
        op = decoded.operation
        audit = independent_balance_audit(row, raw, decoded)
        if not audit["balances_match"]:
            raise ValueError(f"owner balance audit mismatch: {sig}")
        count[f"{op.kind}:{op.quality}"] += 1
        row.update(
            decoder_version=R2_PARSER_VERSION,
            decoded_kind=op.kind,
            decode_quality=op.quality,
            programs=audit["programs"],
            payer=audit["payer"],
            signers=audit["signers"],
            owner_balance_check=True,
            reference_pair_match=R2Decoder._reference_matches(op, ref)
            if len(op.legs) == 2
            else False,
        )
        if op.kind != "swap" or op.quality != "complete":
            continue
        coin = row["coin_mint"]
        leg = next((leg for leg in op.legs if leg.mint == coin), None)
        if leg is None or ref.volume_usd is None or ref.volume_usd <= 0:
            continue
        kind = "buy" if leg.delta_base > 0 else "sell"
        if kind != row["kind_at_pool"]:
            raise ValueError(f"provider direction mismatch: {sig}")
        wallet = row["reported_actor"]
        item = cohort[wallet]
        amount = ref.volume_usd
        item["signatures"].append(sig)
        item["observed_usd"] += amount
        item["per_coin"][coin][f"{kind}s_usd"] += amount
        item["per_coin"][coin]["swaps"] += 1
        time = op.economic_at.isoformat()
        item["first_at"] = min(item["first_at"], time) if item["first_at"] else time
        item["last_at"] = max(item["last_at"], time) if item["last_at"] else time
        events.append(
            {
                "signature": sig,
                "wallet": wallet,
                "coin_mint": coin,
                "direction": kind,
                "reserve_mint": next(leg.mint for leg in op.legs if leg.mint != coin),
                "amount_usd": str(amount),
                "economic_at": time,
                "available_at": receipt.isoformat(),
                "valuation": "geckoterminal_trade_volume_in_usd_at_block_time_exploratory",
                "evidence": "single_supported_swap_owner_delta_matches_provider_pair_and_amounts",
            }
        )
        audits.append(audit)
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    temp.replace(manifest_path)
    output = []
    for wallet, item in cohort.items():
        output.append(
            {
                "wallet": wallet,
                "provenance": "onchain_unattributed",
                "classification": "unknown",
                "first_at": item["first_at"],
                "last_at": item["last_at"],
                "swaps": len(item["signatures"]),
                "signatures": item["signatures"],
                "observed_usd": str(item["observed_usd"]),
                "attributed_between_coins_usd": "0",
                "holding_duration": None,
                "opening_position_unknown": True,
                "per_coin": {
                    k: {a: str(b) for a, b in v.items()} for k, v in item["per_coin"].items()
                },
                "uncertainty": "provider USD estimate; sampled swaps only; related wallets not resolved",
            }
        )
    output.sort(key=lambda x: (-Decimal(x["observed_usd"]), x["wallet"]))
    prior_path = root / "cohort.json"
    prior_known_at = (
        json.loads(prior_path.read_text()).get("cohort_known_at") if prior_path.exists() else None
    )
    return {
        "scope": "exploratory_sample_not_all_solana",
        "decoder_version": R2_PARSER_VERSION,
        "summary": {
            "selected": len(manifest["records"]),
            "fetched": sum(row["status"] == "fetched" for row in manifest["records"]),
            "classification": dict(count),
            "complete_swap_wallets": len(output),
            "coverage_start": min(row["block_at"] for row in manifest["records"]),
            "coverage_end": max(row["block_at"] for row in manifest["records"]),
        },
        "cohort_known_at": prior_known_at or datetime.now(timezone.utc).isoformat(),
        "wallets": output,
        "events": events,
        "manual_balance_audits": audits[:10],
    }


def finalize_corpus(root: str | Path) -> dict:
    """Rebuild the same corpus and durable inferred allocations from archived inputs."""
    from .r2_sequences import SequenceStore

    root = Path(root)
    corpus = verify_corpus(root)
    with SequenceStore(root / "sequences.sqlite") as sequences:
        sequences.add(corpus["events"])
        state = sequences.snapshot()
    per_wallet = defaultdict(lambda: Decimal(0))
    for allocation in state["allocations"]:
        per_wallet[allocation["wallet"]] += Decimal(allocation["amount_usd"])
    for wallet in corpus["wallets"]:
        wallet["attributed_between_coins_usd"] = str(per_wallet[wallet["wallet"]])
        start = datetime.fromisoformat(wallet["first_at"])
        end = datetime.fromisoformat(wallet["last_at"])
        if wallet["swaps"] >= 10 and (end - start).total_seconds() <= 3600:
            wallet["classification"] = "probable_automation_or_arbitrage"
            wallet["classification_reason"] = (
                "at_least_10_complete_swaps_within_1h; not proof of identity"
            )
    corpus["wallets"].sort(
        key=lambda w: (
            -Decimal(w["attributed_between_coins_usd"]),
            -Decimal(w["observed_usd"]),
            w["wallet"],
        )
    )
    corpus["ranking_note"] = (
        "observed sample only; coverage differs by pool and decoder; provider trade USD estimate"
    )
    per_coin = defaultdict(list)
    for wallet in corpus["wallets"]:
        for mint, measure in wallet["per_coin"].items():
            per_coin[mint].append({"wallet": wallet["wallet"], **measure})
    corpus["per_coin_ranking"] = {
        mint: sorted(rows, key=lambda r: -(Decimal(r["buys_usd"]) + Decimal(r["sells_usd"])))
        for mint, rows in per_coin.items()
    }
    (root / "cohort.json").write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n")
    (root / "sequences.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    build_call_manifest(root)
    return corpus


def build_call_manifest(root: str | Path) -> dict:
    root = Path(root)
    budget = json.loads((root / "budget.json").read_text())
    attempts = []
    for item in budget["attempts"]:
        number = item["number"]
        archive = json.loads((root / "source" / f"attempt-{number:04}.json").read_text())
        attempts.append(
            {
                "number": number,
                "phase": "initial_audit" if number <= 120 else "bounded_follow",
                "source": item["source"],
                "request": item["request"],
                "status": item["status"],
                "received_at": archive["received_at"],
                "response_sha256": item.get("response_hash"),
                "response_bytes": len(archive.get("body", "").encode()),
                "archive": f"source/attempt-{number:04}.json",
            }
        )
    follow = (
        json.loads((root / "follow-checkpoint.json").read_text())
        if (root / "follow-checkpoint.json").exists()
        else {"transactions": {}}
    )
    follow_raw = {}
    for signature, item in follow["transactions"].items():
        path = root / "follow-raw" / f"{signature}.json"
        if path.exists():
            follow_raw[signature] = {
                "sha256": _sha(json.loads(path.read_text())),
                "economic_at": item.get("economic_at"),
                "quality": item.get("quality"),
                "kind": item.get("kind"),
                "source_attempt": item.get("receipt", {}).get("attempt"),
            }
    manifest = {
        "dataset": "REAL",
        "scope": "R2_public_sources_only",
        "attempt_count": budget["calls_used"],
        "active_seconds": budget["active_seconds"],
        "cost_usd_billed": "0",
        "attempts": attempts,
        "follow_raw": follow_raw,
        "selected_manifest": "tx-selection.json",
        "cohort": "cohort.json",
        "sequences": "sequences.json",
        "decoder_version": R2_PARSER_VERSION,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
