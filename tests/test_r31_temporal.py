import json
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from rotation.engine import Leg, Operation, Rotation, aggregate_convergence
from rotation.r2_follow import refresh_follow_state
from rotation.r3_pipeline import process_follow
from rotation.r3_registry import ResearchRegistry
from rotation.replay import replay
from rotation.signals import MarketBar, decide

T = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
D = Decimal


def market(mint: str, prices: list[str]) -> list[MarketBar]:
    return [
        MarketBar(
            mint,
            T + timedelta(minutes=i),
            T + timedelta(minutes=i),
            D(price),
            D(100 + i),
            D(20000),
        )
        for i, price in enumerate(prices)
    ]


def swap(
    name: str, source: str, destination: str, economic: datetime, available: datetime
) -> Operation:
    source_amount = 1500 if source == "R" else 100
    destination_amount = 1500 if destination == "R" else 100
    return Operation(
        name,
        "wallet",
        name,
        economic,
        available,
        "swap",
        (
            Leg(source, -source_amount, 0, D(1) if source == "R" else D(15)),
            Leg(destination, destination_amount, 0, D(1) if destination == "R" else D(15)),
        ),
        True,
        "complete",
    )


def test_t1_old_economic_flow_received_now_cannot_be_candidate():
    late = Rotation(
        "A",
        "B",
        "inferred",
        "between_coins",
        D(1500),
        "wallet",
        "sale",
        "buy",
        T - timedelta(days=7),
        T + timedelta(minutes=3),
    )
    decision = decide(
        [late],
        market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"]),
        T + timedelta(minutes=3),
        pair=("A", "B"),
    )
    assert decision.state != "candidate"
    assert "economic_flow_stale" in decision.reasons


def test_t1_clock_boundaries_and_future_evidence_are_explicit():
    at = T + timedelta(minutes=3)
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    allowed = Rotation(
        "A",
        "B",
        "inferred",
        "between_coins",
        D(1500),
        "w",
        "s",
        "b",
        at - timedelta(hours=6),
        at - timedelta(hours=6) + timedelta(minutes=15),
    )
    assert decide([allowed], bars, at, pair=("A", "B")).state == "candidate"
    delayed = Rotation(
        "A",
        "B",
        "inferred",
        "between_coins",
        D(1500),
        "w",
        "s",
        "b",
        at - timedelta(minutes=16),
        at,
    )
    assert "observation_delay_excessive" in decide([delayed], bars, at, pair=("A", "B")).reasons
    future = Rotation(
        "A",
        "B",
        "inferred",
        "between_coins",
        D(1500),
        "w",
        "s",
        "b",
        at + timedelta(minutes=1),
        at + timedelta(minutes=2),
    )
    decision = decide([future], bars, at, pair=("A", "B"))
    assert decision.state != "candidate"
    assert "evidence_not_yet_available" in decision.reasons
    assert "incoherent_or_future_economic_clock" in decision.reasons


def test_t1_aggregate_uses_economic_window_and_observation_delay():
    at = T + timedelta(hours=7)
    stale_sale = swap("sale", "A", "R", T, at)
    fresh_buy = swap("buy", "R", "B", at, at)
    assert aggregate_convergence([stale_sale, fresh_buy], at) == []


def test_old_flow_does_not_emit_new_expiry_revision_at_every_unrelated_bar():
    stale = swap("direct", "A", "B", T - timedelta(days=7), T)
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    result = replay([stale], bars, T + timedelta(minutes=3), eligible_mints={"A", "B"})
    assert len([row for row in result.decisions if row.pair == "A:B"]) == 1
    assert result.decisions[0].decision.state == "expired"


def test_removed_expired_archival_proof_is_not_labelled_market_invalidation():
    stale = swap("direct", "A", "B", T - timedelta(days=7), T)
    retract = Operation(
        "direct",
        "wallet",
        "direct",
        stale.economic_at,
        T + timedelta(minutes=1),
        "retracted",
        (),
        True,
        "complete",
    )
    result = replay([stale, retract], [], T + timedelta(minutes=1), eligible_mints={"A", "B"})
    assert [row.decision.state for row in result.decisions] == ["expired", "observing"]
    assert result.decisions[-1].decision.quality == "proof_removed"


def test_t2_late_buyback_cancels_previously_known_pair_without_rewriting_it():
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    sale = swap("sale", "A", "R", T, T)
    buy_b = swap("buy-b", "R", "B", T + timedelta(minutes=2), T + timedelta(minutes=3))
    buyback = swap("buyback", "R", "A", T + timedelta(minutes=1), T + timedelta(minutes=4))
    before = replay(
        [sale, buy_b],
        bars,
        T + timedelta(minutes=3),
        reserve_mints={"R"},
        eligible_mints={"A", "B"},
    )
    assert [(row.pair, row.decision.state) for row in before.decisions] == [("A:B", "candidate")]
    after = replay(
        [sale, buy_b, buyback],
        bars,
        T + timedelta(minutes=4),
        reserve_mints={"R"},
        eligible_mints={"A", "B"},
    )
    assert after.decisions[: len(before.decisions)] == before.decisions
    assert after.rotations == ()
    assert [(row.at, row.pair, row.decision.state) for row in after.decisions[-1:]] == [
        (T + timedelta(minutes=4), "A:B", "invalidated")
    ]


def test_t2_late_partial_buyback_reduces_proof_and_replay_is_idempotent():
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    sale = swap("sale", "A", "R", T, T)
    buy_b = swap("buy-b", "R", "B", T + timedelta(minutes=2), T + timedelta(minutes=3))
    buyback = Operation(
        "partial",
        "wallet",
        "partial",
        T + timedelta(minutes=1),
        T + timedelta(minutes=4),
        "swap",
        (Leg("R", -600, 0, D(1)), Leg("A", 40, 0, D(15))),
        True,
        "complete",
    )
    before = replay([sale, buy_b], bars, T + timedelta(minutes=3), reserve_mints={"R"})
    after = replay([sale, buy_b, buyback], bars, T + timedelta(minutes=4), reserve_mints={"R"})
    assert before.decisions[0].decision.state == "candidate"
    assert after.decisions[0] == before.decisions[0]
    assert after.rotations[-1].amount_usd == D(900)
    assert after.decisions[-1].at == T + timedelta(minutes=4)
    assert "flow_below_research_threshold" in after.decisions[-1].decision.reasons
    assert (
        replay([sale, buy_b, buyback, buyback], bars, T + timedelta(minutes=4), reserve_mints={"R"})
        == after
    )


def test_t2_expiry_without_new_transactions_and_new_episode_has_new_reference():
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    sale = swap("sale", "A", "R", T, T)
    buy_b = swap("buy-b", "R", "B", T + timedelta(minutes=2), T + timedelta(minutes=3))
    result = replay([sale, buy_b], bars, T + timedelta(hours=7), reserve_mints={"R"})
    assert result.decisions[0].decision.state == "candidate"
    assert any(
        row.decision.state == "expired" and row.at > T + timedelta(hours=6)
        for row in result.decisions
    )


def test_t2_classification_correction_removes_pair_only_when_known():
    payload = json.loads(Path("config/r3-universe.json").read_text())
    base = ResearchRegistry(payload)
    a = base.by_symbol["WIF"]["mint"]
    b = base.by_symbol["FARTCOIN"]["mint"]
    revision_at = T + timedelta(minutes=4)
    payload["classification_revisions"] = [
        {
            "mint": a,
            "status": "excluded",
            "known_at": revision_at.isoformat(),
            "effective_from": T.isoformat(),
            "proof_at": revision_at.isoformat(),
            "proof": {"reason": "synthetic correction"},
        }
    ]
    registry = ResearchRegistry(payload)
    bars = market(a, ["5", "10", "9", "9"]) + market(b, ["10", "5", "5", "5.5"])
    sale = swap("sale", a, "R", T, T)
    buy = swap("buy", "R", b, T + timedelta(minutes=2), T + timedelta(minutes=3))
    before = replay(
        [sale, buy], bars, T + timedelta(minutes=3), reserve_mints={"R"}, registry=registry
    )
    after = replay([sale, buy], bars, revision_at, reserve_mints={"R"}, registry=registry)
    assert before.decisions[0].decision.state == "candidate"
    assert after.decisions[0] == before.decisions[0]
    assert after.decisions[-1].at == revision_at
    assert after.decisions[-1].decision.state == "invalidated"


def test_wallet_identity_correction_replaces_old_actor_only_when_known():
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    first = swap("old", "A", "B", T + timedelta(minutes=2), T + timedelta(minutes=3))
    corrected = Operation(
        "new",
        "verified-wallet",
        "same-signature",
        first.economic_at,
        T + timedelta(minutes=4),
        "swap",
        first.legs,
        True,
        "complete",
        supersedes_id="old",
    )
    before = replay([first], bars, T + timedelta(minutes=3), eligible_mints={"A", "B"})
    after = replay([first, corrected], bars, T + timedelta(minutes=4), eligible_mints={"A", "B"})
    assert after.decisions[0] == before.decisions[0]
    assert len(after.rotations) == 1
    assert after.rotations[0].wallet == "verified-wallet"
    assert after.decisions[-1].at == T + timedelta(minutes=4)
    assert "verified-wallet" in dict(after.decisions[-1].decision.metrics)["evidence_wallets"]


def test_t3_reddecode_cannot_reuse_old_raw_receipt_as_new_proof_time(tmp_path):
    corpus = Path("data/r3-20260927")
    selected = json.loads((corpus / "preselection.json").read_text())["references"]
    row = next(item for item in selected if item["attribution_status"] == "verified_swap")
    signature = row["signature"]
    old_receipt = datetime(2026, 9, 25, tzinfo=timezone.utc)
    root = tmp_path
    (root / "follow-raw").mkdir()
    (root / "follow-raw" / f"{signature}.json").write_bytes(
        (corpus / "raw" / f"{signature}.json").read_bytes()
    )
    (root / "follow-checkpoint.json").write_text(
        json.dumps(
            {
                "started_at": old_receipt.isoformat(),
                "wallets": {row["owner_wallet"]: {}},
                "transactions": {
                    signature: {
                        "status": "fetched",
                        "wallet": row["owner_wallet"],
                        "kind": "unknown",
                        "quality": "partial",
                        "legs": [],
                        "economic_at": row["block_at"],
                        "receipt": {
                            "received_at": old_receipt.isoformat(),
                            "attempt": 1,
                            "response_hash": "raw",
                        },
                    }
                },
                "enrichment_queue": [{"signature": signature, "reason": "partial"}],
            }
        )
    )
    refreshed = refresh_follow_state(root, now=lambda: T + timedelta(days=1))
    revised = refreshed["transactions"][signature]
    assert revised["kind"] == "swap" and revised["quality"] == "complete"
    assert datetime.fromisoformat(revised["effective_available_at"]) == T + timedelta(days=1)
    assert len(revised["decode_revisions"]) == 2
    assert (
        refresh_follow_state(root, now=lambda: T + timedelta(days=2))["transactions"][signature][
            "decode_revisions"
        ]
        == revised["decode_revisions"]
    )


def test_t3_late_price_creates_a_new_valuation_revision_at_receipt(tmp_path):
    registry = ResearchRegistry.load("config/r3-universe.json")
    a = registry.by_symbol["BONK"]["mint"]
    reserve = registry.by_symbol["wSOL"]["mint"]
    (tmp_path / "follow-checkpoint.json").write_text(
        json.dumps(
            {
                "dataset": "DEMO",
                "transactions": {
                    "sig": {
                        "status": "fetched",
                        "wallet": "wallet",
                        "kind": "swap",
                        "quality": "complete",
                        "economic_at": T.isoformat(),
                        "decoded_at": (T + timedelta(minutes=1)).isoformat(),
                        "receipt": {"received_at": T.isoformat()},
                        "legs": [
                            {"mint": reserve, "delta_base": "-100", "decimals": 0},
                            {"mint": a, "delta_base": "100", "decimals": 0},
                        ],
                    }
                },
                "wallets": {"wallet": {"pending_signatures": []}},
                "enrichment_queue": [],
                "gaps": [],
                "stop_reason": "cycle_complete",
            }
        )
    )
    (tmp_path / "cohort.json").write_text(
        json.dumps({"cohort_known_at": (T - timedelta(minutes=1)).isoformat(), "wallets": []})
    )
    (tmp_path / "market-bars.json").write_text(
        json.dumps(
            {
                "dataset": "DEMO",
                "bars": [
                    {
                        "mint": a,
                        "close_at": T.isoformat(),
                        "available_at": (T + timedelta(hours=1)).isoformat(),
                        "price_usd": "2",
                        "volume_usd": "100",
                        "liquidity_usd": None,
                        "interval_seconds": 60,
                        "volume_kind": "interval",
                    }
                ],
            }
        )
    )
    out = tmp_path / "out"
    report = process_follow(tmp_path, registry, output_root=out)
    revisions = report["valuation_revisions"]
    assert [row["valued_legs"] for row in revisions] == [0, 1]
    assert [row["effective_available_at"] for row in revisions] == [
        (T + timedelta(minutes=1)).isoformat(),
        (T + timedelta(hours=1)).isoformat(),
    ]
    assert report == process_follow(tmp_path, registry, output_root=out)
    state = json.loads((tmp_path / "follow-checkpoint.json").read_text())
    state["transactions"]["sig"]["identity_revisions"] = [
        {
            "wallet": "corrected-wallet",
            "known_at": (T + timedelta(hours=2)).isoformat(),
            "proof_at": (T + timedelta(hours=3)).isoformat(),
            "proof": "DEMO dated owner audit",
        }
    ]
    (tmp_path / "follow-checkpoint.json").write_text(json.dumps(state))
    corrected = process_follow(tmp_path, registry, output_root=out)
    assert corrected["valuation_revisions"][:2] == revisions
    assert (
        corrected["valuation_revisions"][-1]["effective_available_at"]
        == (T + timedelta(hours=3)).isoformat()
    )
    assert corrected["valuation_revisions"][-1]["wallet"] == "corrected-wallet"
    assert corrected["valuation_revisions"][-1]["supersedes_id"].endswith(":wallet")
    state["dataset"] = "REAL"
    (tmp_path / "follow-checkpoint.json").write_text(json.dumps(state))
    market_payload = json.loads((tmp_path / "market-bars.json").read_text())
    market_payload["dataset"] = "REAL"
    (tmp_path / "market-bars.json").write_text(json.dumps(market_payload))
    with pytest.raises(ValueError, match="public address and evidence reference"):
        process_follow(tmp_path, registry, output_root=out)


def test_t3_real_legacy_decode_clock_is_not_backdated_to_raw_receipt(tmp_path):
    root = Path("data/r3-20260927")
    for name in ("follow-checkpoint.json", "cohort.json", "market-bars.json"):
        shutil.copy2(root / name, tmp_path / name)
    report = process_follow(
        tmp_path, ResearchRegistry.load("config/r3-universe.json"), output_root=tmp_path / "r31"
    )
    assert report["dataset"] == "REAL"
    assert report["unknown_decode_time_signatures"]
    assert report["stages"]["post_freeze_complete_swaps"] == 1
    assert report["stages"]["usable_complete_swaps"] == 0
    assert "legacy_decode_availability_unknown" in report["missing_transitions"]
