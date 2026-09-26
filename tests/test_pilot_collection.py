import json
from pathlib import Path

import pytest

from rotation.pilot_collection import run_pilot_collection

CORPUS = Path("data/real-pilot-20260926")


def test_collection_workflow_restarts_from_files_without_refetch(tmp_path):
    class Gecko:
        calls = 0

        def token_pools(self, mint):
            self.calls += 1
            return json.loads((CORPUS / "jup-pools.json").read_text())

        def trades(self, pool):
            self.calls += 1
            name = "jup-sol-trades.json" if pool.startswith("C8Gr") else "jup-usdc-trades.json"
            return json.loads((CORPUS / name).read_text())

        def ohlcv(self, pool, mint, limit=30):
            self.calls += 1
            name = (
                "jup-sol-ohlcv.json"
                if mint.startswith("JUP")
                else "sol-usd-ohlcv.json"
                if mint.startswith("So111")
                else "usdc-usd-ohlcv.json"
            )
            payload = json.loads((CORPUS / name).read_text())
            return payload.get("response", payload)

    class Rpc:
        calls = 0

        def transaction(self, signature):
            self.calls += 1
            return json.loads((CORPUS / "raw" / f"{signature}.json").read_text())

    gecko, rpc = Gecko(), Rpc()
    first = run_pilot_collection(tmp_path, gecko=gecko, rpc=rpc, per_pool=1)
    before = (gecko.calls, rpc.calls)
    second = run_pilot_collection(tmp_path, gecko=gecko, rpc=rpc, per_pool=1)
    assert first["transactions_fetched"] == 2
    assert second["transactions_fetched"] == 2
    assert (gecko.calls, rpc.calls) == before
    assert (tmp_path / "budget.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert all(
        row.get("raw_received_at") and row.get("decoded_at")
        for row in json.loads((tmp_path / "manifest.json").read_text())["records"]
    )
    with pytest.raises(ValueError, match="cannot change pilot protocol"):
        run_pilot_collection(tmp_path, gecko=gecko, rpc=rpc, per_pool=2)
    assert (gecko.calls, rpc.calls) == before
