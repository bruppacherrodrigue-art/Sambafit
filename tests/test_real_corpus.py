import json
from datetime import datetime, timezone
from decimal import Decimal

from rotation.market import TradeRef
from rotation.pilot import collect_corpus


def test_corpus_restarts_without_duplicate_fetch_and_preserves_raw_hash(tmp_path):
    at = datetime(2026, 9, 26, tzinfo=timezone.utc)
    signature = "1" * 88
    refs = [
        TradeRef(
            signature, 1, at, "actor", "buy", "A", "B", Decimal(1), Decimal(2), Decimal(3), "pool"
        )
    ]

    class Rpc:
        calls = 0

        def transaction(self, signature):
            self.calls += 1
            return {
                "slot": 1,
                "blockTime": int(at.timestamp()),
                "version": 0,
                "transaction": {"signatures": [signature]},
            }

    rpc = Rpc()
    first = collect_corpus(refs, rpc, tmp_path)
    second = collect_corpus(refs, rpc, tmp_path)
    assert rpc.calls == 1
    assert first == second
    assert first["records"][0]["status"] == "fetched"
    raw = json.loads((tmp_path / "raw" / f"{signature}.json").read_text())
    assert raw["transaction"]["signatures"] == [signature]


def test_unavailable_signature_is_a_checkpoint_not_an_implicit_retry(tmp_path):
    at = datetime(2026, 9, 26, tzinfo=timezone.utc)
    ref = TradeRef("2" * 88, 1, at, None, "buy", "A", "B", Decimal(1), Decimal(2), None, "pool")

    class Rpc:
        calls = 0

        def transaction(self, signature):
            self.calls += 1
            return None

    rpc = Rpc()
    first = collect_corpus([ref], rpc, tmp_path)
    second = collect_corpus([ref], rpc, tmp_path)
    assert rpc.calls == 1
    assert first == second
    assert first["records"][0]["status"] == "unavailable"
