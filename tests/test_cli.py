import json
import os
import uuid

from rotation.cli import main
from rotation.store import Store

URL = os.getenv("TEST_DATABASE_URL", "postgresql://rotation:rotation@127.0.0.1:55432/rotation")


def test_pilot_collect_cli_requires_explicit_output_and_stays_db_independent(
    monkeypatch, capsys, tmp_path
):
    captured = {}

    def fake_collect(output, *, per_pool, rpc_url):
        captured.update(output=output, per_pool=per_pool, rpc_url=rpc_url)
        return {"attempts_total": 0}

    monkeypatch.setattr("rotation.cli.run_pilot_collection", fake_collect)
    assert main(["pilot-collect", "--output", str(tmp_path), "--per-pool", "2"]) == 0
    assert captured == {"output": str(tmp_path), "per_pool": 2, "rpc_url": None}
    assert json.loads(capsys.readouterr().out)["attempts_total"] == 0


def test_cli_doctor_seed_replay_and_report(capsys, monkeypatch, tmp_path):
    schema = "test_" + uuid.uuid4().hex[:12]
    store = Store(URL, schema=schema)
    store.migrate()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("ROTATION_SCHEMA", schema)
    try:
        assert main(["doctor"]) == 0
        assert main(["demo-seed"]) == 0
        config = tmp_path / "experiment.yaml"
        config.write_text("dataset: DEMO\nuntil: 2026-01-01T12:03:00Z\n")
        assert main(["replay", "--config", str(config)]) == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        run = json.loads(lines[-1])
        assert run["dataset"] == "DEMO" and run["status"] == "completed"
        assert set(run["comparison"]) == {"basket", "market_only", "wallets_only", "combined"}
        assert store.list_signals("DEMO")
        assert store.list_signals("REPLAY") == []
        assert main(["report", "--run-id", run["run_id"]]) == 0
        assert "synthetic" in capsys.readouterr().out
        paper_config = tmp_path / "paper.yaml"
        paper_config.write_text("dataset: DEMO\ninitial_cash: '1000'\n")
        assert main(["paper", "--config", str(paper_config)]) == 0
        paper = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert paper["filled_orders"] == 2
        assert float(paper["ending_cash"]) < 1000
    finally:
        store.drop_test_schema()
