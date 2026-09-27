import json
from pathlib import Path

from rotation.r2_follow import follow_once, refresh_follow_state


def setup_root(tmp_path, wallets):
    root = tmp_path / "data" / "r2-20260926"
    root.mkdir(parents=True)
    config = tmp_path / "config"
    config.mkdir()
    (config / "r2-candidates.json").write_bytes(Path("config/r2-candidates.json").read_bytes())
    (root / "cohort.json").write_text(json.dumps({"wallets": [{"wallet": w} for w in wallets]}))
    return root


def tx(signature):
    return {
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": [], "instructions": []},
        },
        "meta": {"err": None, "fee": 5000, "preTokenBalances": [], "postTokenBalances": []},
        "blockTime": 1790000000,
        "slot": 1,
        "version": 0,
    }


def receipt(number):
    return {
        "received_at": "2026-09-27T10:00:00+00:00",
        "attempt": number,
        "response_hash": str(number),
    }


def test_follow_paginates_more_than_twenty_and_services_second_wallet(tmp_path):
    root = setup_root(tmp_path, ["wallet1", "wallet2"])
    first = [f"s{i:02}" for i in range(25)]

    class Fake:
        archive = root / "source"
        next_attempt = 0

        def rpc(self, method, params):
            self.next_attempt += 1
            if method == "getSignaturesForAddress":
                wallet, options = params
                if wallet == "wallet1":
                    page = first[20:] if options.get("before") == first[19] else first[:20]
                else:
                    page = ["second"]
                return [{"signature": s} for s in page], receipt(self.next_attempt)
            return tx(params[0]), receipt(self.next_attempt)

    state = follow_once(
        root,
        Fake(),
        wallets_limit=2,
        pools_limit=0,
        transactions_limit=2,
        pages_limit=2,
    )
    assert len(state["wallets"]["wallet1"]["pending_signatures"]) >= 23
    assert set(state["transactions"]) == {"s00", "second"}
    assert {row["signature"] for row in state["enrichment_queue"]} == {"s00", "second"}
    assert all(row["source_hash"] for row in state["enrichment_queue"])
    refreshed = refresh_follow_state(root)
    assert {row["signature"] for row in refreshed["enrichment_queue"]} == {"s00", "second"}
    assert state["wallets"]["wallet1"]["scan_cursor"] is None
    assert not state["gaps"]


def test_rpc_null_is_retried_and_not_marked_seen(tmp_path):
    root = setup_root(tmp_path, ["wallet1"])

    class Fake:
        archive = root / "source"
        tx_calls = 0

        def rpc(self, method, params):
            if method == "getSignaturesForAddress":
                return [{"signature": "retry"}], receipt(1)
            self.tx_calls += 1
            return (None if self.tx_calls == 1 else tx("retry")), receipt(self.tx_calls + 1)

    fake = Fake()
    first = follow_once(root, fake, wallets_limit=1, pools_limit=0, transactions_limit=1)
    assert first["transactions"]["retry"]["status"] == "unavailable"
    assert "retry" not in first["wallets"]["wallet1"]["seen"]
    second = follow_once(root, fake, wallets_limit=1, pools_limit=0, transactions_limit=1)
    assert second["transactions"]["retry"]["status"] == "fetched"
    assert fake.tx_calls == 2
