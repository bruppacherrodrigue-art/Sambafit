import json
from datetime import datetime, timezone

import httpx
import pytest

from rotation.r2_budget import R2Budget
from rotation.r2_sources import R2Http, R2SourceError

T = datetime(2026, 9, 26, 9, tzinfo=timezone.utc)


def test_429_is_archived_and_counted_without_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"errors": [{"status": "429"}]})

    budget = R2Budget(tmp_path / "budget.json", now=lambda: T)
    with budget.session("audit", max_calls=3, max_seconds=30) as session:
        client = R2Http(
            session,
            tmp_path / "source",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            min_interval_seconds=0,
        )
        with pytest.raises(R2SourceError, match="HTTP 429"):
            client.gecko("/networks/solana/pools", {"page": 1})
    assert len(calls) == 1
    state = budget.snapshot()
    assert state["calls_used"] == 1
    assert state["attempts"][0]["status"] == "http_429"
    archives = list((tmp_path / "source").glob("*.json"))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())["http_status"] == 429


def test_rpc_only_allows_read_methods_and_archives_result(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert body["method"] == "getTransaction"
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"slot": 1}})

    budget = R2Budget(tmp_path / "budget.json", now=lambda: T)
    with budget.session("audit", max_calls=3, max_seconds=30) as session:
        client = R2Http(
            session,
            tmp_path / "source",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            min_interval_seconds=0,
        )
        with pytest.raises(ValueError, match="read-only"):
            client.rpc("sendTransaction", ["secret"])
        result, receipt = client.rpc("getTransaction", ["signature", {"encoding": "jsonParsed"}])
    assert result == {"slot": 1}
    assert receipt["received_at"] and receipt["response_hash"]
    assert budget.snapshot()["calls_used"] == 1


def test_pool_search_requires_explicit_solana_network(tmp_path):
    def handler(request):
        assert request.url.path == "/api/v2/search/pools"
        assert request.url.params["network"] == "solana"
        return httpx.Response(200, json={"data": []})

    budget = R2Budget(tmp_path / "budget.json", now=lambda: T)
    with budget.session("audit", max_calls=1, max_seconds=30) as session:
        client = R2Http(
            session,
            tmp_path / "source",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            min_interval_seconds=0,
        )
        with pytest.raises(ValueError, match="Solana"):
            client.gecko("/search/pools", {"query": "BONK", "network": "base"})
        payload, _ = client.gecko("/search/pools", {"query": "BONK", "network": "solana"})
        assert payload["data"] == []
    assert budget.snapshot()["calls_used"] == 1
