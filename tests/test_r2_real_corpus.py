import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from rotation.api import create_app
from rotation.r2_corpus import finalize_corpus
from rotation.r2_universe import build_universe

ROOT = Path("data/r2-20260926")


def test_real_r2_archive_has_ten_independent_owner_checks_and_replays_identically(tmp_path):
    copied = tmp_path / "r2"
    shutil.copytree(ROOT, copied)
    first = finalize_corpus(copied)
    sequence_before = json.loads((copied / "sequences.json").read_text())
    second = finalize_corpus(copied)
    assert first == second
    assert sequence_before == json.loads((copied / "sequences.json").read_text())
    assert first["summary"]["selected"] == 66
    assert first["summary"]["classification"]["swap:complete"] == 18
    assert len(first["manual_balance_audits"]) == 10
    for audit in first["manual_balance_audits"]:
        assert audit["actor_signed"] and audit["balances_match"]
        assert audit["decoded_kind"] == "swap" and audit["fee_lamports"] > 0
    assert len(sequence_before["allocations"]) == 3


def test_universe_is_a_research_proposal_and_r2_api_exposes_real_proof_only(tmp_path, monkeypatch):
    universe = build_universe(ROOT)
    assert sum(row["status"] == "research_candidate" for row in universe["records"]) == 11
    assert any(
        row["symbol"] == "PUMP" and row["status"] == "research_excluded"
        for row in universe["records"]
    )
    copied = tmp_path / "data" / "r2-20260926"
    shutil.copytree(ROOT, copied)
    shutil.copytree("config", tmp_path / "config")
    monkeypatch.setenv("ROTATION_R2_DIR", str(copied))
    client = TestClient(create_app(object()))
    assert client.get("/api/r2/universe").json()["scope"] == "research_proposal_not_user_watchlist"
    cohort = client.get("/api/r2/cohort").json()
    assert len(cohort["wallets"]) == 3
    signature = cohort["wallets"][0]["signatures"][0]
    evidence = client.get(f"/api/r2/evidence/{signature}").json()
    assert evidence["dataset"] == "REAL" and evidence["selection"]["source_hash"]
    assert client.get("/api/r2/evidence/DEMO-s1").status_code == 404
    assert client.get("/api/r2/budget").json()["calls_used"] == 206
    follow = client.get("/api/r2/follow").json()
    assert len(follow["transactions"]) == 75
    assert follow["opening_positions_unknown"] is True
