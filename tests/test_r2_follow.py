import json
from pathlib import Path

from rotation.r2_follow import follow_once, refresh_follow_state

ROOT = Path("data/r2-20260926")


def test_follow_cycle_persists_checkpoint_without_duplicate_tx(tmp_path):
    target = tmp_path / "data" / "r2-20260926"
    target.mkdir(parents=True)
    config = tmp_path / "config"
    config.mkdir()
    (config / "r2-candidates.json").write_bytes(Path("config/r2-candidates.json").read_bytes())
    cohort = json.loads((ROOT / "cohort.json").read_text())
    cohort["wallets"] = cohort["wallets"][:1]
    (target / "cohort.json").write_text(json.dumps(cohort))
    signature = cohort["wallets"][0]["signatures"][0]
    tx = json.loads((ROOT / "raw" / f"{signature}.json").read_text())
    search = json.loads((ROOT / "source" / "attempt-0003.json").read_text())
    pool = json.loads(search["body"])["data"][0]
    search_wif = json.loads((ROOT / "source" / "attempt-0004.json").read_text())
    pool_wif = json.loads(search_wif["body"])["data"][0]

    class Fake:
        archive = target / "source"
        tx_calls = 0

        def rpc(self, method, params):
            if method == "getSignaturesForAddress":
                return [{"signature": signature}], {
                    "received_at": "2026-09-26T10:00:00+00:00",
                    "attempt": 1,
                    "response_hash": "h",
                }
            assert method == "getTransaction"
            self.tx_calls += 1
            return tx, {
                "received_at": "2026-09-26T10:00:01+00:00",
                "attempt": 2,
                "response_hash": "h",
            }

        def gecko(self, path):
            return {"data": pool if pool["attributes"]["address"] in path else pool_wif}, {
                "received_at": "2026-09-26T10:00:02+00:00",
                "attempt": 3,
                "response_hash": "h",
            }

    fake = Fake()
    first = follow_once(target, fake, wallets_limit=1, pools_limit=1, transactions_limit=1)
    second = follow_once(target, fake, wallets_limit=1, pools_limit=1, transactions_limit=1)
    assert first["stop_reason"] == second["stop_reason"] == "cycle_complete"
    assert fake.tx_calls == 1
    assert len(second["transactions"]) == 1
    assert len(second["market_snapshots"]) == 2
    assert second["transactions"][signature]["usd_value"] is None
    rebuilt = refresh_follow_state(target)
    assert rebuilt["opening_positions_unknown"] is True
    assert rebuilt["observable_inventory_delta_base"] == second["observable_inventory_delta_base"]
