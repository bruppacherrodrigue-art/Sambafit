from pathlib import Path

from fastapi.testclient import TestClient

from rotation.api import create_app


def test_r3_api_is_real_only_and_exposes_pair_proof(monkeypatch):
    monkeypatch.setenv("ROTATION_R3_DIR", str(Path("data/r3-20260927").resolve()))
    client = TestClient(create_app(object()))
    universe = client.get("/api/r3/universe").json()
    assert universe["scope"] == "research_only_not_user_approved"
    cohort = client.get("/api/r3/cohort").json()
    assert cohort["scope"] == "wallet_candidates_in_sample_not_all_solana"
    replay = client.get("/api/r3/replay").json()
    assert replay["dataset"] == "REAL" and replay["synthetic"] is False
    prospective = client.get("/api/r3/prospective").json()
    assert prospective["dataset"] == "REAL" and prospective["paper_orders"] == []
    assert len(prospective["incomplete_operations"]) == 12
    partial_signature = prospective["incomplete_operations"][0]["signature"]
    assert client.get(f"/api/r3/operations/{partial_signature}").json()["dataset"] == "REAL"
    signature = cohort["wallets"][0]["sample_signatures"][0]
    evidence = client.get(f"/api/r3/operations/{signature}").json()
    assert evidence["dataset"] == "REAL"
    assert evidence["operation"]["signature"] == signature
    assert evidence["raw"]["transaction"]["signatures"][0] == signature
    target = next(row for row in universe["records"] if row["role"] == "target")
    market = client.get(f"/api/r3/market/{target['mint']}").json()
    assert market and all(row["dataset"] == "REAL" for row in market)
    followed_mint = next(row["mint"] for row in universe["records"] if row["symbol"] == "WIF")
    followed_market = client.get(f"/api/r3/market/{followed_mint}").json()
    assert followed_market and all(row["dataset"] == "REAL" for row in followed_market)
    reserve = next(row for row in universe["records"] if row["role"] == "reserve")
    assert client.get(f"/api/r3/market/{reserve['mint']}").status_code == 404
    assert client.get("/api/r3/operations/DEMO-s1").status_code == 404
