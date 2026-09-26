import json
from datetime import datetime, timezone

import httpx

from rotation.r2_budget import R2Budget
from rotation.r2_collect import collect_selected_transactions
from rotation.r2_sources import R2Http

T = datetime(2026, 9, 26, 9, tzinfo=timezone.utc)
SIGNATURE = "1" * 88


def _selection(root):
    (root / "tx-selection.json").write_text(
        json.dumps(
            {"records": [{"signature": SIGNATURE, "reported_actor": "actor", "status": "pending"}]}
        )
    )


def test_transaction_checkpoint_is_idempotent_after_restart(tmp_path):
    _selection(tmp_path)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {"slot": 7, "transaction": {"signatures": [SIGNATURE]}},
            },
        )

    budget = R2Budget(tmp_path / "budget.json", now=lambda: T)
    for _ in range(2):
        with budget.session("tx", max_calls=2, max_seconds=30) as session:
            http = R2Http(
                session,
                tmp_path / "source",
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                min_interval_seconds=0,
            )
            collect_selected_transactions(tmp_path, http, limit=1)
    assert len(calls) == 1
    assert budget.snapshot()["calls_used"] == 1
    row = json.loads((tmp_path / "tx-selection.json").read_text())["records"][0]
    assert row["status"] == "fetched" and row["response_hash"]
    assert json.loads((tmp_path / "raw" / f"{SIGNATURE}.json").read_text())["slot"] == 7


def test_archived_rpc_response_recovers_without_second_call(tmp_path):
    _selection(tmp_path)
    archive = tmp_path / "source"
    archive.mkdir()
    (archive / "attempt-0001.json").write_text(
        json.dumps(
            {
                "request": f"getTransaction:{SIGNATURE}",
                "received_at": T.isoformat(),
                "http_status": 200,
                "response_hash": "archived",
                "body": json.dumps(
                    {"result": {"slot": 9, "transaction": {"signatures": [SIGNATURE]}}}
                ),
            }
        )
    )
    budget = R2Budget(tmp_path / "budget.json", now=lambda: T)
    with budget.session("recovery", max_calls=1, max_seconds=30) as session:
        http = R2Http(session, archive, min_interval_seconds=0)
        collect_selected_transactions(tmp_path, http, limit=1)
    assert budget.snapshot()["calls_used"] == 0
    row = json.loads((tmp_path / "tx-selection.json").read_text())["records"][0]
    assert row["status"] == "fetched"
    assert json.loads((tmp_path / "raw" / f"{SIGNATURE}.json").read_text())["slot"] == 9
