import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from rotation.r3_pipeline import process_follow, replay_r2_attribution, replay_verified_corpus
from rotation.r3_registry import ResearchRegistry


def test_r2_real_archive_replays_three_attributions_with_changed_destination_and_amount(tmp_path):
    registry = ResearchRegistry.load("config/r3-universe.json")
    report = replay_r2_attribution(Path("data/r2-20260926"), tmp_path, registry)
    assert report["r2_allocation_count"] == 3
    assert report["r3_allocation_count"] == 3
    assert sum(row["change"] == "amount_changed" for row in report["comparison"]) == 1
    assert sum(row["change"] == "new" for row in report["comparison"]) == 1
    assert sum(row["change"] == "removed" for row in report["comparison"]) == 1
    assert all(
        row["r3_reserve_quantity_base"] is not None
        for row in report["comparison"]
        if row["change"] != "removed"
    )


def test_r3_real_corpus_replay_is_deterministic_without_synthetic_prices(tmp_path):
    registry = ResearchRegistry.load("config/r3-universe.json")
    first = replay_verified_corpus("data/r3-20260927", tmp_path, registry)
    second = replay_verified_corpus("data/r3-20260927", tmp_path, registry)
    assert first == second
    assert first["dataset"] == "REAL"
    assert first["synthetic"] is False
    assert first["verified_operations"] == 20
    assert first["price_study_status"] in {"missing_market", "stale_market"}
    assert not any(row["state"] == "confirmed" for row in first["decisions"])


def test_synthetic_follow_chain_reaches_pair_decision_without_execution(tmp_path):
    registry = ResearchRegistry.load("config/r3-universe.json")
    a = registry.by_symbol["WIF"]["mint"]
    b = registry.by_symbol["FARTCOIN"]["mint"]
    reserve = registry.by_symbol["wSOL"]["mint"]
    start = datetime.fromisoformat(registry.known_at) + timedelta(hours=1)
    txs = {}
    for sig, offset, legs in (
        ("sale", 3, [(a, -200), (reserve, 100)]),
        ("buy", 4, [(reserve, -100), (b, 300)]),
    ):
        txs[sig] = {
            "status": "fetched",
            "wallet": "wallet",
            "kind": "swap",
            "quality": "complete",
            "economic_at": (start + timedelta(minutes=offset)).isoformat(),
            "receipt": {"received_at": (start + timedelta(minutes=5)).isoformat()},
            "legs": [
                {"mint": mint, "delta_base": str(delta), "decimals": 0} for mint, delta in legs
            ],
        }
    (tmp_path / "follow-checkpoint.json").write_text(
        json.dumps(
            {
                "dataset": "DEMO",
                "transactions": txs,
                "wallets": {"wallet": {"pending_signatures": []}},
                "gaps": [],
                "stop_reason": "cycle_complete",
            }
        )
    )
    (tmp_path / "cohort.json").write_text(
        json.dumps({"cohort_known_at": (start - timedelta(minutes=1)).isoformat()})
    )
    bars = []
    for mint, values in ((a, (5, 10, 9, 9, 9)), (b, (10, 5, 5, 5.5, 5.6))):
        for i, value in enumerate(values):
            bars.append(
                {
                    "mint": mint,
                    "close_at": (start + timedelta(minutes=i)).isoformat(),
                    "available_at": (start + timedelta(minutes=5)).isoformat(),
                    "price_usd": str(Decimal(str(value))),
                    "volume_usd": "100",
                    "liquidity_usd": None,
                    "interval_seconds": 60,
                    "volume_kind": "interval",
                }
            )
    (tmp_path / "market-bars.json").write_text(json.dumps({"dataset": "DEMO", "bars": bars}))
    first = process_follow(tmp_path, registry)
    second = process_follow(tmp_path, registry)
    assert first == second
    assert first["dataset"] == "DEMO" and first["synthetic"] is True
    assert first["stages"]["reserve_reconciled"] == 2
    assert first["stages"]["target_rotations"] == 1
    assert any(row["state"] == "candidate" for row in first["decisions"])
    assert all(row["strategy"]["admission"] == "blocked" for row in first["decisions"])
    assert all(row["strategy"]["paper_status"] == "blocked" for row in first["decisions"])
    assert first["execution_status"] == "blocked_no_historical_depth_or_quote"
    prior_decisions = first["decisions"]
    bars.append(
        {
            "mint": b,
            "close_at": (start + timedelta(minutes=4)).isoformat(),
            "available_at": (start + timedelta(minutes=15)).isoformat(),
            "price_usd": "1000",
            "volume_usd": "100",
            "liquidity_usd": None,
            "interval_seconds": 60,
            "volume_kind": "interval",
        }
    )
    (tmp_path / "market-bars.json").write_text(json.dumps({"dataset": "DEMO", "bars": bars}))
    later = process_follow(tmp_path, registry)
    assert [
        row for row in later["decisions"] if row["at"] <= (start + timedelta(minutes=5)).isoformat()
    ] == prior_decisions
