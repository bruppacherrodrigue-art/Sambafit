from datetime import datetime, timezone

from rotation.collect import backfill_wallet


class FakeRpc:
    def __init__(self):
        self.calls = 0
        self.before_seen = []

    def signatures(self, address, limit, before=None):
        self.calls += 1
        self.before_seen.append(before)
        if before:
            return []
        return [{"signature": "sig2", "slot": 2}, {"signature": "sig1", "slot": 1}]

    def transaction(self, signature):
        self.calls += 1
        return {
            "slot": 2,
            "blockTime": 1767225600,
            "version": 0,
            "transaction": {"signatures": [signature], "message": {"instructions": []}},
            "meta": {
                "err": None,
                "fee": 5000,
                "preTokenBalances": [],
                "postTokenBalances": [],
                "innerInstructions": [],
            },
        }


class FakeStore:
    def __init__(self):
        self.raw = {}
        self.checkpoints = {}
        self.operations = {}
        self.gaps = []

    def get_checkpoint(self, key):
        return self.checkpoints.get(key)

    def add_raw(self, signature, wallet, payload, source, parser_version, first_seen_at=None):
        key = (signature, wallet)
        inserted = key not in self.raw
        self.raw[key] = payload
        return inserted

    def add_operation(self, signature, wallet, operation, fee_lamports, decoder_version):
        self.operations[(signature, wallet)] = operation

    def checkpoint(self, key, cursor, pages, coverage):
        self.checkpoints[key] = {"cursor": cursor, "pages": pages, "coverage": coverage}

    def add_coverage_gap(self, wallet, reason, start_at=None):
        self.gaps.append(reason)


def test_backfill_pages_checkpoint_replay_idempotent_and_records_partial_coverage():
    rpc, store = FakeRpc(), FakeStore()
    first = backfill_wallet(
        store,
        rpc,
        "wallet",
        page_size=2,
        max_pages=1,
        max_calls=3,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert first["new_raw"] == 2
    assert store.get_checkpoint("wallet|wallet")["cursor"] == "sig1"
    assert len(store.operations) == 2
    assert "token accounts" in store.gaps[0]
    second = backfill_wallet(
        store,
        rpc,
        "wallet",
        page_size=2,
        max_pages=1,
        max_calls=3,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert second["new_raw"] == 0
    assert rpc.before_seen == [None, "sig1"]
