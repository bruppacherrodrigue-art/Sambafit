"""Frozen public RPC fixtures. No network calls during these tests."""

import os
import shutil
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from rotation.api import _operations, create_app
from rotation.engine import attribute_rotations
from rotation.real_corpus import (
    JUP,
    METEORA_DLMM,
    USDC,
    WSOL,
    import_corpus,
    load_verified,
    summarize_corpus,
    verify_manifest,
    verify_source_receipts,
)
from rotation.replay import replay
from rotation.research import price_operations
from rotation.signals import MarketBar
from rotation.store import Store

ROOT = "data/real-pilot-20260926"
URL = os.getenv("TEST_DATABASE_URL", "postgresql://rotation:rotation@127.0.0.1:55432/rotation")


def test_reverification_of_frozen_manifest_does_not_change_it(tmp_path):
    copied = tmp_path / "corpus"
    shutil.copytree(ROOT, copied)
    before = (copied / "manifest.json").read_bytes()
    verify_manifest(copied)
    assert (copied / "manifest.json").read_bytes() == before


def test_frozen_rpc_hashes_and_ten_independent_owner_balance_checks():
    assert verify_source_receipts(ROOT) == 8
    summary = summarize_corpus(ROOT)
    swaps = [a for a in summary["audits"] if a["decoded_kind"] == "swap"]
    assert summary["transactions_fetched"] == 60
    assert summary["decoded_swaps"] == 18
    assert summary["wallets_with_complete_swaps"] == 5
    assert summary["balance_mismatches"] == []
    assert len(swaps) >= 10
    for item in swaps[:10]:
        assert item["actor_signed"] and item["balances_match"]
        assert METEORA_DLMM in item["programs"] and item["fee_lamports"] > 0
        assert len(item["raw_owner_deltas"]) == 2


def test_real_multi_swap_route_is_quarantined_and_v1_partial_is_not_false_swap():
    by_sig = {row["signature"]: (row, tx, decoded) for row, tx, decoded in load_verified(ROOT)}
    route = next(value for signature, value in by_sig.items() if signature.startswith("5H819kiETE"))
    assert route[2].operation.kind == "unknown"
    assert route[2].operation.quality == "partial_route"
    assert len(route[2].operation.legs) == 2
    assert len(attribute_rotations([route[2].operation])) == 0  # No historical USD quote.
    partial = next(
        value for signature, value in by_sig.items() if signature.startswith("2Mi4dLygRs")
    )
    assert partial[1]["version"] == 1
    assert partial[2].operation.kind == "unknown"
    assert partial[2].operation.quality == "partial"


def test_real_import_replay_recovery_and_api_dataset_isolation():
    schema = "test_" + uuid.uuid4().hex[:12]
    store = Store(URL, schema)
    store.migrate()
    try:
        first = import_corpus(store, ROOT)
        second = import_corpus(store, ROOT)
        assert first["raw_inserted"] == 60 and second["raw_inserted"] == 0
        assert first["market_bars_inserted"] == 89 and second["market_bars_inserted"] == 0
        assert store.overview("REAL")["open_gaps"] == 3
        until = datetime(2026, 9, 26, 7, 11, tzinfo=timezone.utc)
        operations = _operations(store.list_operations(until, "REAL"))
        bars = [
            MarketBar(
                r["mint"],
                r["close_at"],
                r["available_at"],
                r["price_usd"],
                r["volume_usd"],
                r["liquidity_usd"],
            )
            for r in store.all_market_bars(until, "REAL")
        ]
        assert len(operations) == 60 and len(bars) == 89
        priced = price_operations(operations, bars)
        options = {
            "stable_mints": {USDC},
            "reserve_mints": {WSOL},
            "eligible_mints": {JUP, USDC, WSOL},
        }
        a = replay(priced, bars, until, **options)
        b = replay(priced, bars, until, **options)
        assert a == b
        assert all(r.direction != "between_coins" for r in a.rotations)
        client = TestClient(create_app(store))
        signature = store.list_operations(until, "REAL")[0]["signature"]
        assert len(client.get("/api/operations?dataset=REAL").json()) == 60
        rotations = client.get("/api/rotations?dataset=REAL").json()
        assert all(
            r["source"] in {JUP, USDC, WSOL} and r["destination"] in {JUP, USDC, WSOL}
            for r in rotations
        )
        assert all(r["direction"] != "between_coins" for r in rotations)
        assert client.get("/api/operations?dataset=DEMO").json() == []
        assert client.get(f"/api/evidence/{signature}?dataset=DEMO").status_code == 404
        proof = client.get(f"/api/evidence/{signature}?dataset=REAL").json()
        assert proof["raw"]["response_hash"] and proof["operation"]["decoder_version"]
        context = client.get(f"/api/operation-context/{signature}?dataset=REAL").json()
        assert context["dataset"] == "REAL"
        assert context["decision"]["state"] == "observing"
        assert context["market_features"]
    finally:
        store.drop_test_schema()
