"""One attribution/feature/decision path for real archived and followed operations."""

import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .comparison import compare_variants
from .engine import Leg, Operation
from .market import parse_candles
from .r2_decode import R2Decoder
from .r2_sequences import SequenceStore
from .r3_registry import ADDRESS, ResearchRegistry
from .replay import replay
from .research import price_operations, study_events
from .signals import MarketBar
from .strategy import assess_strategy, load_strategy_config

RESERVE_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temp, path)


def replay_r2_attribution(
    r2_root: str | Path, output_root: str | Path, registry: ResearchRegistry
) -> dict:
    """Rebuild identical 18 R2 trades with reserve base units, preserving R2 artifacts."""
    r2_root, output_root = Path(r2_root), Path(output_root)
    old = _json(r2_root / "sequences.json")["allocations"]
    events = []
    for event in _json(r2_root / "cohort.json")["events"]:
        tx = _json(r2_root / "raw" / f"{event['signature']}.json")
        decoded = R2Decoder().decode(
            tx, event["wallet"], datetime.fromisoformat(event["available_at"])
        )
        reserve = next(
            (leg for leg in decoded.operation.legs if leg.mint == event["reserve_mint"]),
            None,
        )
        if reserve is None or reserve.delta_base == 0:
            continue
        events.append(
            {
                **event,
                "reserve_quantity_base": str(abs(reserve.delta_base)),
                "reserve_decimals": reserve.decimals,
            }
        )
    eligible = registry.eligible_mints(datetime.fromisoformat(registry.known_at))
    with SequenceStore(output_root / "r2-r3-sequences.sqlite", eligible_mints=eligible) as store:
        store.add(events)
        snapshot = store.snapshot()
    prior = {(row["source_signature"], row["destination_signature"]): row for row in old}
    current = {
        (row["source_signature"], row["destination_signature"]): row
        for row in snapshot["allocations"]
    }
    comparison = []
    for key in sorted(prior.keys() | current.keys()):
        before, after = prior.get(key), current.get(key)
        before_usd = Decimal(before["amount_usd"]) if before else None
        after_usd = Decimal(after["amount_usd"]) if after and after["amount_usd"] else None
        change = (
            "new"
            if before is None
            else "removed"
            if after is None
            else "amount_changed"
            if abs(after_usd - before_usd) > Decimal("0.01")
            else "same_pair"
        )
        comparison.append(
            {
                "source_signature": key[0],
                "destination_signature": key[1],
                "source_mint": (after or before)["source_mint"],
                "destination_mint": (after or before)["destination_mint"],
                "r2_usd_proxy": str(before_usd) if before_usd is not None else None,
                "r3_usd_convention": str(after_usd) if after_usd is not None else None,
                "r3_reserve_quantity_base": after["reserve_quantity_base"] if after else None,
                "change": change,
            }
        )
    report = {
        "dataset": "REAL",
        "mode": "retrospective_exploration_not_past_bot_decisions",
        "r2_event_count": len(events),
        "r2_allocation_count": len(old),
        "r3_allocation_count": len(snapshot["allocations"]),
        "comparison": comparison,
        "r3_snapshot": snapshot,
    }
    _write(output_root / "r2-comparison.json", report)
    return report


def load_r2_market_bars(r2_root: str | Path) -> list[MarketBar]:
    root = Path(r2_root)
    bars = []
    for path in sorted((root / "source").glob("attempt-*.json")):
        archive = _json(path)
        request = archive.get("request", "")
        if "/ohlcv/minute" not in request or archive.get("http_status") != 200:
            continue
        pool = request.split("/pools/")[1].split("/ohlcv/")[0]
        mint = request.split('"token": "')[1].split('"')[0]
        received = datetime.fromisoformat(archive["received_at"])
        for candle in parse_candles(json.loads(archive["body"]), pool, mint, received, 60):
            bars.append(
                MarketBar(
                    mint,
                    candle.close_at,
                    candle.received_at,
                    candle.close_usd,
                    candle.volume_usd,
                    None,
                    interval_seconds=60,
                    volume_kind="interval",
                )
            )
    return bars


def _verified_operations(root: Path, registry: ResearchRegistry) -> list[Operation]:
    selected = _json(root / "preselection.json")
    known_at = datetime.fromisoformat(registry.known_at)
    operations = []
    for row in selected["references"]:
        if row["attribution_status"] != "verified_swap":
            continue
        volume = Decimal(row["provider_volume_usd"])
        legs = []
        for item in row["legs"]:
            quantity = Decimal(abs(int(item["delta_base"]))) / (Decimal(10) ** item["decimals"])
            legs.append(
                Leg(
                    item["mint"],
                    int(item["delta_base"]),
                    int(item["decimals"]),
                    volume / quantity if quantity else None,
                )
            )
        available_at = max(datetime.fromisoformat(row["raw_received_at"]), known_at)
        operations.append(
            Operation(
                f"solana:{row['signature']}:0:{row['owner_wallet']}",
                row["owner_wallet"],
                row["signature"],
                datetime.fromisoformat(row["block_at"]),
                available_at,
                "swap",
                tuple(legs),
                True,
                "complete",
            )
        )
    return operations


def replay_verified_corpus(
    r3_root: str | Path,
    output_root: str | Path,
    registry: ResearchRegistry,
    *,
    r2_root: str | Path = "data/r2-20260926",
) -> dict:
    root, output_root = Path(r3_root), Path(output_root)
    strategy_config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy-r3-1.json"
    )
    cohort = _json(root / "cohort.json")
    operations = _verified_operations(root, registry)
    bars = load_r2_market_bars(r2_root)
    until = max(
        [operation.available_at for operation in operations] + [bar.available_at for bar in bars],
        default=datetime.fromisoformat(registry.known_at),
    )
    result = replay(
        operations,
        bars,
        until,
        reserve_mints=RESERVE_MINTS,
        stable_mints={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
        registry=registry,
        policy=strategy_config.pair_policy,
    )
    targets = [
        rotation
        for rotation in result.rotations
        if rotation.direction == "between_coins"
        and rotation.source in registry.eligible_mints(rotation.available_at)
        and rotation.destination in registry.eligible_mints(rotation.available_at)
    ]
    universe = registry.eligible_mints(until) & {bar.mint for bar in bars}
    comparison = (
        compare_variants(targets, bars, Decimal("1000"), universe, strategy_config.pair_policy)
        if universe
        else None
    )
    rows = [
        {
            "at": record.at.isoformat(),
            "pair": record.pair,
            "state": record.decision.state,
            "quality": record.decision.quality,
            "score": record.decision.score,
            "components": dict(record.decision.components),
            "metrics": dict(record.decision.metrics),
            "reasons": list(record.decision.reasons),
            "execution_quality": record.decision.execution_quality,
            "version": record.decision.version,
            "strategy": asdict(
                assess_strategy(
                    *record.pair.split(":", 1),
                    record.decision,
                    bars,
                    record.at,
                    registry.records_at(record.at),
                    cohort,
                    strategy_config.strategy_policy,
                )
            ),
        }
        for record in result.decisions
    ]
    report = {
        "dataset": "REAL",
        "mode": "REPLAY",
        "synthetic": False,
        "selection_bias": "retrospective_cohort_from_same_sample",
        "registry_version": registry.version,
        "strategy_version": strategy_config.version,
        "strategy_config_hash": strategy_config.sha256,
        "availability_clock_quality": "raw_receipt_lower_bound_decoder_timestamp_unknown",
        "verified_operations": len(operations),
        "closed_market_bars": len(bars),
        "target_rotations": len(targets),
        "rotations": [
            {
                **asdict(rotation),
                "economic_at": rotation.economic_at.isoformat(),
                "available_at": rotation.available_at.isoformat(),
            }
            for rotation in targets
        ],
        "pairs_evaluated": sorted({record.pair for record in result.decisions}),
        "decisions": rows,
        "price_study_status": (
            "missing_market"
            if not bars
            else "stale_market"
            if not any(row["state"] in {"candidate", "confirmed"} for row in rows)
            else "descriptive_only"
        ),
        "event_study": study_events(result, bars),
        "comparators": comparison,
        "financial_edge": None,
        "execution_evidence": "historical_depth_and_quotes_unavailable",
    }
    _write(output_root / "replay.json", report)
    return report


def process_follow(
    root: str | Path, registry: ResearchRegistry, *, output_root: str | Path | None = None
) -> dict:
    """Process persisted prospective inputs through the same replay functions."""
    root = Path(root)
    strategy_config = load_strategy_config(
        Path(__file__).resolve().parents[2] / "config" / "strategy-r3-1.json"
    )
    follow = _json(root / "follow-checkpoint.json")
    dataset = follow.get("dataset", "REAL")
    if dataset not in {"REAL", "DEMO"}:
        raise ValueError("follow dataset must be REAL or DEMO")
    market_path = root / "market-bars.json"
    market = _json(market_path) if market_path.exists() else {"dataset": dataset, "bars": []}
    if market["dataset"] != dataset:
        raise ValueError("market and transaction datasets differ")
    cohort = _json(root / "cohort.json")
    frozen_at = datetime.fromisoformat(cohort["cohort_known_at"])
    bars = [
        MarketBar(
            row["mint"],
            datetime.fromisoformat(row["close_at"]),
            datetime.fromisoformat(row["available_at"]),
            Decimal(row["price_usd"]),
            Decimal(row["volume_usd"]) if row["volume_usd"] is not None else None,
            Decimal(row["liquidity_usd"]) if row.get("liquidity_usd") is not None else None,
            row.get("interval_seconds", 60),
            row.get("volume_kind", "interval"),
        )
        for row in market["bars"]
    ]
    fetched = [row for row in follow["transactions"].values() if row["status"] == "fetched"]
    strict = [
        row for row in fetched if row.get("kind") == "swap" and row.get("quality") == "complete"
    ]
    post_freeze = [row for row in strict if datetime.fromisoformat(row["economic_at"]) >= frozen_at]
    operations = []
    valuation_revisions = []
    unknown_decode_time = []
    reserve_reconciled = 0
    for row in post_freeze:
        wallet = row["wallet"]
        signature = next((sig for sig, item in follow["transactions"].items() if item is row), None)
        if signature is None:
            raise ValueError("follow signature missing")
        legs = tuple(
            Leg(item["mint"], int(item["delta_base"]), int(item["decimals"]), None)
            for item in row["legs"]
        )
        reserve_legs = [leg for leg in legs if leg.mint in RESERVE_MINTS and leg.delta_base != 0]
        target_legs = [
            leg
            for leg in legs
            if leg.mint
            in registry.eligible_mints(datetime.fromisoformat(row["receipt"]["received_at"]))
        ]
        if len(reserve_legs) == 1 and len(target_legs) == 1 and len(legs) == 2:
            reserve_reconciled += 1
        economic_at = datetime.fromisoformat(row["economic_at"])
        raw_available = datetime.fromisoformat(row["receipt"]["received_at"])
        effective_available = datetime.fromisoformat(
            row.get("effective_available_at", row["receipt"]["received_at"])
        )
        if "effective_available_at" not in row and "decoded_at" not in row:
            unknown_decode_time.append(signature)
            if dataset == "REAL":
                # Receipt is only a lower bound for a legacy parse. It cannot
                # certify when the new proof was first usable by a live bot.
                continue
        if row.get("decoded_at"):
            effective_available = max(
                effective_available, datetime.fromisoformat(row["decoded_at"])
            )
        effective_available = max(effective_available, raw_available)

        def identity_available(revision: dict) -> datetime:
            return max(
                datetime.fromisoformat(revision["known_at"]),
                datetime.fromisoformat(revision["proof_at"]),
            )

        identity_revisions = list(row.get("identity_revisions", []))
        for revision in identity_revisions:
            if (
                not revision.get("proof")
                or not revision.get("wallet")
                or not revision.get("proof_at")
            ):
                raise ValueError("wallet identity correction needs explicit dated proof")
            if dataset == "REAL" and (
                not ADDRESS.fullmatch(revision["wallet"])
                or not isinstance(revision["proof"], dict)
                or not revision["proof"].get("reference")
                or not revision["proof"].get("type")
            ):
                raise ValueError(
                    "REAL wallet correction needs public address and evidence reference"
                )
            identity_available(revision)
        identity_revisions.sort(key=identity_available)
        initial_wallet = wallet
        for revision in identity_revisions:
            if identity_available(revision) <= effective_available:
                initial_wallet = revision["wallet"]
        operation = Operation(
            f"solana:{signature}:0:{initial_wallet}",
            initial_wallet,
            signature,
            economic_at,
            effective_available,
            "swap",
            legs,
            True,
            "complete",
        )
        # Each later close/correction is a new knowledge revision of the same operation.
        # Replay replaces the canonical id at that availability; it never backdates it.
        revision_times = sorted(
            {effective_available}
            | {
                identity_available(revision)
                for revision in identity_revisions
                if identity_available(revision) > effective_available
            }
            | {
                bar.available_at
                for bar in bars
                if bar.available_at > effective_available
                and bar.close_at <= economic_at
                and bar.mint in {leg.mint for leg in legs}
            }
        )
        previous_legs = None
        for revision_at in revision_times:
            prior_identity_id = operation.id
            for identity in identity_revisions:
                if identity_available(identity) != revision_at:
                    continue
                next_wallet = identity["wallet"]
                if next_wallet != operation.wallet:
                    operation = replace(
                        operation,
                        wallet=next_wallet,
                        id=f"solana:{signature}:0:{next_wallet}",
                    )
            identity_changed = operation.id != prior_identity_id
            if identity_changed:
                operation = replace(operation, supersedes_id=prior_identity_id)
            revised = price_operations([replace(operation, available_at=revision_at)], bars)[0]
            if revised.legs == previous_legs and not identity_changed:
                continue
            operations.append(revised)
            if identity_changed:
                operation = replace(operation, supersedes_id=None)
            previous_legs = revised.legs
            valuation_revisions.append(
                {
                    "operation_id": revised.id,
                    "wallet": revised.wallet,
                    "supersedes_id": revised.supersedes_id,
                    "identity_proof_known_at": revision_at.isoformat()
                    if identity_changed
                    else None,
                    "raw_received_at": raw_available.isoformat(),
                    "decoded_at": row.get("decoded_at"),
                    "effective_available_at": revision_at.isoformat(),
                    "valued_legs": sum(leg.usd_price is not None for leg in revised.legs),
                    "knowledge_time_quality": "observed"
                    if signature not in unknown_decode_time
                    else "legacy_unknown",
                }
            )
    until = max(
        [op.available_at for op in operations] + [bar.available_at for bar in bars],
        default=frozen_at,
    )
    result = replay(
        operations,
        bars,
        until,
        reserve_mints=RESERVE_MINTS,
        stable_mints={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
        registry=registry,
        policy=strategy_config.pair_policy,
    )
    targets = [
        rotation
        for rotation in result.rotations
        if rotation.direction == "between_coins"
        and rotation.source in registry.eligible_mints(rotation.available_at)
        and rotation.destination in registry.eligible_mints(rotation.available_at)
    ]
    decisions = [
        {
            "at": item.at.isoformat(),
            "pair": item.pair,
            "state": item.decision.state,
            "quality": item.decision.quality,
            "score": item.decision.score,
            "components": dict(item.decision.components),
            "metrics": dict(item.decision.metrics),
            "reasons": list(item.decision.reasons),
            "version": item.decision.version,
            "execution_quality": item.decision.execution_quality,
            "strategy": asdict(
                assess_strategy(
                    *item.pair.split(":", 1),
                    item.decision,
                    bars,
                    item.at,
                    registry.records_at(item.at),
                    cohort,
                    strategy_config.strategy_policy,
                )
            ),
        }
        for item in result.decisions
    ]
    reasons = []
    if not strict:
        reasons.append("no_supported_complete_swap")
    if follow.get("enrichment_queue"):
        reasons.append("incomplete_operations_await_enrichment")
    if unknown_decode_time:
        reasons.append("legacy_decode_availability_unknown")
    if strict and not post_freeze:
        reasons.append("no_post_cohort_freeze_swap")
    if not targets:
        reasons.append("no_verified_memecoin_to_memecoin_rotation")
    if not bars:
        reasons.append("missing_pair_market_bars")
    if targets and not decisions:
        reasons.append("no_pair_decision")
    report = {
        "dataset": dataset,
        "mode": "PAPER LIVE",
        "synthetic": dataset == "DEMO",
        "registry_version": registry.version,
        "strategy_version": strategy_config.version,
        "strategy_config_hash": strategy_config.sha256,
        "availability_clock_quality": "per_operation_observed_or_legacy_unknown",
        "cohort_frozen_at": frozen_at.isoformat(),
        "stages": {
            "queued_signatures": sum(
                len(info.get("pending_signatures", [])) for info in follow["wallets"].values()
            ),
            "transactions_fetched": len(fetched),
            "incomplete_enrichment": len(follow.get("enrichment_queue", [])),
            "complete_swaps": len(strict),
            "post_freeze_complete_swaps": len(post_freeze),
            "usable_complete_swaps": len({operation.id for operation in operations}),
            "reserve_reconciled": reserve_reconciled,
            "target_rotations": len(targets),
            "market_bars": len(bars),
            "pairs_evaluated": len({row["pair"] for row in decisions}),
            "candidate_decisions": sum(row["state"] == "candidate" for row in decisions),
            "confirmed_decisions": sum(row["state"] == "confirmed" for row in decisions),
        },
        "coverage_gaps": follow.get("gaps", []),
        "unknown_decode_time_signatures": unknown_decode_time,
        "valuation_revisions": valuation_revisions,
        "incomplete_operations": follow.get("enrichment_queue", []),
        "stop_reason": follow.get("stop_reason"),
        "missing_transitions": reasons,
        "rotations": [
            {
                **asdict(rotation),
                "economic_at": rotation.economic_at.isoformat(),
                "available_at": rotation.available_at.isoformat(),
            }
            for rotation in targets
        ],
        "decisions": decisions,
        "execution_status": "blocked_no_historical_depth_or_quote",
        "paper_orders": [],
        "financial_edge": None,
    }
    _write(Path(output_root or root) / "prospective.json", report)
    return report
