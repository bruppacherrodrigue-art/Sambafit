from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Leg, Operation
from rotation.replay import replay
from rotation.signals import MarketBar

T = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
D = Decimal


def market(mint, values):
    return [
        MarketBar(
            mint,
            T + timedelta(minutes=i),
            T + timedelta(minutes=i),
            D(str(price)),
            D(100 + i),
            D(20000),
        )
        for i, price in enumerate(values)
    ]


def swap(source, destination, wallet):
    at = T + timedelta(minutes=3)
    return Operation(
        f"{source}-{destination}-{wallet}",
        wallet,
        f"{source}-{destination}-{wallet}",
        at,
        at,
        "swap",
        (Leg(source, -100, 0, D(15)), Leg(destination, 100, 0, D(15))),
        True,
        "complete",
    )


def test_replay_emits_two_pair_decisions_and_future_changes_do_not_rewrite_them():
    bars = market("A", [5, 10, 9, 9]) + market("C", [5, 10, 9, 9]) + market("B", [10, 5, 5, 5.5])
    operations = [swap("A", "B", "w1"), swap("C", "B", "w2")]
    first = replay(operations, bars, T + timedelta(minutes=3), eligible_mints={"A", "B", "C"})
    assert {r.pair for r in first.decisions} == {"A:B", "C:B"}
    assert {r.decision.state for r in first.decisions} == {"candidate"}
    later = replay(
        operations,
        bars
        + [
            MarketBar(
                "B", T + timedelta(minutes=4), T + timedelta(minutes=4), D(1), D(100), D(20000)
            )
        ],
        T + timedelta(minutes=4),
        eligible_mints={"A", "B", "C"},
    )
    assert tuple(r for r in later.decisions if r.at <= T + timedelta(minutes=3)) == first.decisions
