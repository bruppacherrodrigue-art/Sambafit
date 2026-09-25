"""Explicitly synthetic scenario; fixed timestamps and separate DEMO dataset."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .engine import Leg, Operation
from .replay import replay
from .signals import MarketBar
from .store import digest

BASE = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def scenario():
    d = Decimal
    operations = [
        Operation(
            "DEMO-s1",
            "DEMO-W1",
            "DEMO-s1",
            BASE,
            BASE,
            "swap",
            (Leg("DEMO-A", -100, 0, d("100")), Leg("DEMO-B", 100, 0, d("100"))),
            True,
            "complete",
        ),
        Operation(
            "DEMO-s2",
            "DEMO-W2",
            "DEMO-s2",
            BASE + timedelta(minutes=1),
            BASE + timedelta(minutes=1),
            "swap",
            (Leg("DEMO-A", -100, 0, d("100")), Leg("DEMO-B", 100, 0, d("100"))),
            True,
            "complete",
        ),
        Operation(
            "DEMO-incomplete",
            "DEMO-W3",
            "DEMO-incomplete",
            BASE + timedelta(minutes=3),
            BASE + timedelta(minutes=3),
            "unknown",
            (Leg("DEMO-C", -10, 0, None),),
            True,
            "partial",
        ),
    ]
    bars = [
        MarketBar(
            mint,
            BASE + timedelta(minutes=i),
            BASE + timedelta(minutes=i),
            d(price),
            d("100000"),
            d("1000000"),
        )
        for mint, prices in (
            ("DEMO-B", ("100", "100", "105", "80", "75")),
            ("DEMO-A", ("100", "100", "100", "100", "100")),
        )
        for i, price in enumerate(prices)
    ]
    return operations, bars


def seed_demo(store) -> dict:
    operations, bars = scenario()
    for index, op in enumerate(operations):
        raw = {
            "slot": index + 1,
            "blockTime": int(op.economic_at.timestamp()),
            "synthetic": True,
            "signature": op.signature,
        }
        store.add_raw(
            op.signature,
            op.wallet,
            raw,
            "synthetic_fixture",
            "demo-1",
            first_seen_at=op.available_at,
            dataset="DEMO",
        )
        store.add_operation(op.signature, op.wallet, op, 0, "demo-1", dataset="DEMO")
    for bar in bars:
        store.add_market_bar(
            bar.mint,
            bar.close_at,
            bar.available_at,
            bar.close_usd,
            bar.volume_usd,
            bar.liquidity_usd,
            "synthetic_fixture",
            "DEMO",
        )
    result = replay(operations, bars, BASE + timedelta(minutes=4))
    config_hash = digest({"scenario": "synthetic-demo-1", "score": "hypothesis-1"})
    for record in result.decisions:
        store.record_decision(
            record.pair,
            record.at,
            record.decision.state,
            record.decision.quality,
            record.decision.score,
            dict(record.decision.components),
            config_hash,
            "DEMO",
            list(record.decision.reasons),
        )
    store.record_decision(
        "DEMO-A:DEMO-C",
        BASE + timedelta(minutes=3),
        "observing",
        "missing_market",
        0,
        {},
        config_hash,
        "DEMO",
        ["synthetic incomplete operation; no market data"],
    )
    return {
        "dataset": "DEMO",
        "operations": len(operations),
        "bars": len(bars),
        "decisions": len(result.decisions) + 1,
        "synthetic": True,
    }
