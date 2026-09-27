from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from rotation.r3_cohort import build_manifest, select_references, verify_selected
from rotation.r3_registry import ResearchRegistry


def test_prefilter_uses_common_window_and_largest_dated_references():
    registry = ResearchRegistry.load("config/r3-universe.json")
    result = select_references(
        Path("data/r2-20260926"), registry, min_usd=Decimal(500), max_refs=24
    )
    assert result["scope"] == "sample_preselection_not_qualified_wallets"
    assert result["threshold_usd"] == "500"
    assert len(result["references"]) <= 24
    amounts = [Decimal(row["provider_volume_usd"]) for row in result["references"]]
    assert amounts == sorted(amounts, reverse=True)
    assert all(amount >= 500 for amount in amounts)
    assert len({row["signature"] for row in result["references"]}) == len(amounts)
    assert all(row["attribution_status"] == "unverified" for row in result["references"])
    start = datetime.fromisoformat(result["common_window"]["start"])
    end = datetime.fromisoformat(result["common_window"]["end"])
    assert start < end < datetime.now(timezone.utc)
    assert all(
        start <= datetime.fromisoformat(row["block_at"]) <= end for row in result["references"]
    )
    assert len(result["pool_coverage"]) == 10


def test_new_real_corpus_has_independent_owner_balance_checks():
    result = verify_selected("data/r3-20260927")
    assert result["verified_swaps"] >= 10
    assert result["balance_mismatches"] == []
    assert result["reference_mismatches"] == []
    assert all(row["actor_signed"] for row in result["audits"])


def test_r3_manifest_hashes_real_raw_and_preserves_partial_status():
    root = Path("data/r3-20260927")
    result = build_manifest(root)
    assert result["dataset"] == "REAL"
    assert result["calls_used"] == len(result["attempts"])
    assert any(row["decode_status"] == "partial" for row in result["transactions"])
    for row in result["transactions"]:
        if row["raw_file"]:
            raw = root / row["raw_file"]
            assert row["raw_file_sha256"] == sha256(raw.read_bytes()).hexdigest()
            assert row["programs"]
