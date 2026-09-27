import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rotation.engine import Leg, Operation
from rotation.r3_registry import ResearchRegistry
from rotation.replay import replay
from rotation.signals import MarketBar


def test_registry_uses_exact_mints_and_availability_dates():
    registry = ResearchRegistry.load("config/r3-universe.json")
    known = datetime.fromisoformat(registry.known_at)
    assert registry.eligible_mints(known - timedelta(seconds=1)) == set()
    eligible = registry.eligible_mints(known)
    assert len(eligible) >= 8
    assert all(registry.by_mint[mint]["network"] == "solana" for mint in eligible)
    assert all(registry.by_mint[mint]["category"] == "memecoin" for mint in eligible)
    assert registry.by_symbol["PENGU"]["status"] == "uncertain"
    assert registry.by_symbol["PUMP"]["mint"] not in eligible
    assert registry.by_symbol["JUP"]["mint"] not in eligible
    assert registry.by_symbol["USDC"]["mint"] not in eligible
    assert registry.by_symbol["wSOL"]["mint"] not in eligible
    assert registry.eligible_mints(datetime.now(timezone.utc) + timedelta(days=1)) == eligible


def test_invalid_network_or_missing_source_cannot_be_admitted(tmp_path):
    value = json.loads(Path("config/r3-universe.json").read_text())
    value["records"][0]["network"] = "ethereum"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="Solana"):
        ResearchRegistry.load(path)
    value["records"][0]["network"] = "solana"
    value["records"][0]["proof"] = None
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="proof"):
        ResearchRegistry.load(path)


def test_replay_cannot_backdate_new_memecoin_classification():
    registry = ResearchRegistry.load("config/r3-universe.json")
    a, b = sorted(registry.eligible_mints(datetime.fromisoformat(registry.known_at)))[:2]
    before = datetime.fromisoformat(registry.known_at) - timedelta(minutes=1)
    operation = Operation(
        "historical",
        "wallet",
        "historical",
        before,
        before,
        "swap",
        (Leg(a, -100, 0, None), Leg(b, 100, 0, None)),
        True,
        "complete",
    )
    bar = MarketBar(b, before, before, 1, 1, None)
    assert replay([operation], [bar], before, registry=registry).rotations == ()
