import os
import uuid

from fastapi.testclient import TestClient

from rotation.api import create_app
from rotation.demo import seed_demo
from rotation.store import Store

URL = os.getenv("TEST_DATABASE_URL", "postgresql://rotation:rotation@127.0.0.1:55432/rotation")


def test_demo_data_is_visible_only_in_demo_dataset(monkeypatch):
    store = Store(URL, schema="test_" + uuid.uuid4().hex[:12])
    store.migrate()
    try:
        seed_demo(store)
        client = TestClient(create_app(store))
        demo = client.get("/api/overview", params={"dataset": "DEMO"}).json()
        real = client.get("/api/overview", params={"dataset": "REAL"}).json()
        assert demo["raw_events"] > 0 and demo["signals"] > 0
        assert real["raw_events"] == 0 and real["signals"] == 0
        assert client.get("/api/signals", params={"dataset": "REAL"}).json() == []
        assert client.get("/api/signals", params={"dataset": "DEMO"}).json()
        assert client.get("/api/evidence/DEMO-s1", params={"dataset": "REAL"}).status_code == 404
        evidence = client.get("/api/evidence/DEMO-s1", params={"dataset": "DEMO"}).json()
        assert evidence["raw"]["payload"]["synthetic"] is True
        store.import_wallets([{"address": "11111111111111111111111111111111"}])
        assert client.get("/api/overview", params={"dataset": "DEMO"}).json()["wallets"] == 0
        assert client.get("/api/overview", params={"dataset": "REAL"}).json()["wallets"] == 1
        monkeypatch.setenv("DATABASE_URL", URL)
        monkeypatch.setenv("ROTATION_SCHEMA", store.schema)
        assert (
            TestClient(create_app()).get("/api/overview", params={"dataset": "DEMO"}).status_code
            == 200
        )
    finally:
        store.drop_test_schema()
