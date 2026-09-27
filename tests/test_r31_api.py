import json

from fastapi.testclient import TestClient

from rotation.api import create_app


def test_r31_api_keeps_offline_replay_separate_from_r3_and_demo(monkeypatch, tmp_path):
    monkeypatch.setenv("ROTATION_R31_DIR", str(tmp_path))
    client = TestClient(create_app(object()))
    assert client.get("/api/r3-1/replay").status_code == 404
    real = {
        "dataset": "REAL",
        "mode": "REPLAY",
        "synthetic": False,
        "decisions": [{"state": "invalidated", "at": "2026-09-27T10:04:00+00:00"}],
    }
    (tmp_path / "replay.json").write_text(json.dumps(real))
    (tmp_path / "prospective.json").write_text(
        json.dumps({"dataset": "REAL", "mode": "PAPER LIVE", "paper_orders": []})
    )
    assert client.get("/api/r3-1/replay").json() == real
    assert client.get("/api/r3-1/prospective").json()["paper_orders"] == []
    assert client.get("/api/r3-1/strategy").json()["version"] == "r3.1-strategy-hypothesis-1"
    (tmp_path / "replay.json").write_text(json.dumps({"dataset": "DEMO", "synthetic": True}))
    assert client.get("/api/r3-1/replay").status_code == 409
