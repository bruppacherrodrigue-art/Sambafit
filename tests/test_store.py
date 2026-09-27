import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from rotation.engine import Leg, Operation
from rotation.store import Store

URL = os.getenv("TEST_DATABASE_URL", "postgresql://rotation:rotation@127.0.0.1:55432/rotation")


@pytest.fixture
def store():
    schema = "test_" + uuid.uuid4().hex[:12]
    db = Store(URL, schema=schema)
    db.migrate()
    yield db
    db.drop_test_schema()


def test_import_versions_proof_and_no_pseudonym_attribution(store):
    watch = [
        {
            "network": "solana",
            "mint": "So11111111111111111111111111111111111111112",
            "symbol": "SOL",
            "decimals": 9,
            "eligible_from": "2026-01-01T00:00:00Z",
        }
    ]
    version = store.import_watchlist(watch, known_at="2026-01-01T00:00:00Z")
    assert store.import_watchlist(watch, known_at="2026-01-01T00:00:00Z") == version
    assert store.list_tokens()[0]["mint"] == watch[0]["mint"]
    with pytest.raises(ValueError):
        store.import_wallets([{"address": "abc", "fomo_profile": "someone"}])
    store.import_wallets(
        [
            {
                "address": "11111111111111111111111111111111",
                "fomo_profile": "someone",
                "proof": "https://example.test/proof",
                "verified_at": "2026-01-01T00:00:00Z",
                "confidence": "manual",
            }
        ]
    )
    assert store.list_wallets()[0]["confidence"] == "manual"


def test_raw_dedup_checkpoint_and_persisted_decision(store):
    raw = {"slot": 10, "meta": {"fee": 5000}}
    assert store.add_raw("sig", "wallet", raw, "rpc", "parser-1") is True
    assert store.add_raw("sig", "wallet", raw, "rpc", "parser-1") is False
    store.checkpoint("wallet", "sig", 1, "partial")
    assert store.get_checkpoint("wallet")["cursor"] == "sig"
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert (
        store.record_decision("A:B", at, "candidate", "complete", 42, {"flow": 12}, "hash", "DEMO")
        is True
    )
    assert (
        store.record_decision("A:B", at, "candidate", "complete", 42, {"flow": 12}, "hash", "DEMO")
        is False
    )
    assert len(store.list_signals("DEMO")) == 1
    assert store.list_signals("REPLAY") == []


def test_market_and_operations_respect_availability_and_dataset(store):
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.add_market_bar(
        "B", at, at, Decimal("2"), Decimal("100"), Decimal("10000"), "fixture", "DEMO"
    )
    store.add_market_bar(
        "B", at, at, Decimal("999"), Decimal("100"), Decimal("10000"), "real", "REAL"
    )
    assert [b["price_usd"] for b in store.list_market_bars("B", at, "DEMO")] == [Decimal("2")]
    assert store.list_market_bars("B", at, "REPLAY") == []
    with pytest.raises(ValueError, match="before close"):
        store.add_market_bar(
            "B", at + timedelta(minutes=1), at, Decimal("2"), Decimal("100"), None, "bad", "REAL"
        )


def test_r3_classification_is_versioned_and_mint_keyed(store):
    from rotation.r3_registry import ResearchRegistry

    registry = ResearchRegistry.load("config/r3-universe.json")
    assert store.import_research_registry(registry) == 15
    assert store.import_research_registry(registry) == 0
    rows = store.list_research_registry(registry.version)
    assert len(rows) == 15
    assert {
        r["mint"] for r in rows if r["status"] == "research_candidate"
    } == registry.eligible_mints(datetime.fromisoformat(registry.known_at))


def test_latest_decoder_version_and_wallet_scoped_evidence(store):
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for wallet in ("w1", "w2"):
        store.add_raw(
            "shared",
            wallet,
            {"slot": 1, "blockTime": int(at.timestamp()), "owner": wallet},
            "rpc",
            "v1",
        )
        first = Operation("shared", wallet, "shared", at, at, "unknown", (), True, "partial")
        last = Operation(
            "shared",
            wallet,
            "shared",
            at,
            at,
            "swap",
            (Leg("A", -10, 0, Decimal(1)), Leg("B", 10, 0, Decimal(1))),
            True,
            "complete",
        )
        store.add_operation("shared", wallet, first, 0, "v1", decoded_at=at)
        store.add_operation("shared", wallet, last, 0, "v2", decoded_at=at + timedelta(seconds=1))
    assert len(store.list_operations(at)) == 2
    assert all(row["decoder_version"] == "v1" for row in store.list_operations(at))
    assert all(
        row["decoder_version"] == "v2" for row in store.list_operations(at + timedelta(seconds=1))
    )
    assert store.get_evidence("shared", "REAL", "w2")["raw"]["payload"]["owner"] == "w2"


def test_two_economic_operations_in_one_signature_remain_distinct(store):
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.add_raw("shared-signature", "w1", {"slot": 1}, "rpc", "v1")
    for index, destination in enumerate(("B", "C")):
        operation = Operation(
            f"solana:shared-signature:{index}:w1",
            "w1",
            "shared-signature",
            at,
            at,
            "swap",
            (Leg("A", -10, 0, None), Leg(destination, 10, 0, None)),
            True,
            "complete",
        )
        store.add_operation(
            "shared-signature",
            "w1",
            operation,
            0,
            "v1",
            decoded_at=at,
            operation_index=index,
        )
    rows = store.list_operations(at)
    assert {row["canonical_id"] for row in rows} == {
        "solana:shared-signature:0:w1",
        "solana:shared-signature:1:w1",
    }
    assert {row["legs"][1]["mint"] for row in rows} == {"B", "C"}


def test_existing_demo_operations_repaired_for_historical_replay(store):
    from rotation.demo import seed_demo

    seed_demo(store)
    at = datetime(2026, 1, 1, 12, 4, tzinfo=timezone.utc)
    with store.connect() as conn:
        conn.execute("UPDATE operations SET decoded_at=now()")
        conn.execute("DELETE FROM schema_migrations WHERE version=3")
    assert store.list_operations(at, "DEMO") == []
    store.migrate()
    assert len(store.list_operations(at, "DEMO")) == 3
