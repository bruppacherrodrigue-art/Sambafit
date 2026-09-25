from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Leg, Operation
from rotation.replay import replay
from rotation.signals import MarketBar, decide

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = Decimal


def swap(name, wallet, at):
    return Operation(
        name,
        wallet,
        name,
        at,
        at,
        "swap",
        (Leg("A", -100, 0, D("100")), Leg("B", 100, 0, D("100"))),
        True,
        "complete",
    )


def bar(at, price):
    return MarketBar("B", at, at, D(price), D("100000"), D("1000000"))


def test_replay_and_direct_share_decision_and_ignore_future_bar_changes():
    operations = [swap("s1", "w1", T)]
    bars = [bar(T, "100")]
    first = replay(operations, bars, T + timedelta(minutes=1))
    expected = decide(first.rotations, bars, T)
    assert first.decisions[0].decision == expected
    future = replay(
        operations, bars + [bar(T + timedelta(hours=1), "100000")], T + timedelta(minutes=1)
    )
    assert first.decisions == future.decisions


def test_false_signal_invalidates_only_after_loss_observed():
    operations = [swap("s1", "w1", T), swap("s2", "w2", T + timedelta(minutes=1))]
    bars = [
        bar(T, "100"),
        bar(T + timedelta(minutes=1), "100"),
        bar(T + timedelta(minutes=2), "80"),
    ]
    result = replay(operations, bars, T + timedelta(minutes=2))
    assert [record.decision.state for record in result.decisions] == [
        "candidate",
        "confirmed",
        "invalidated",
    ]
    assert result.decisions[-1].at == T + timedelta(minutes=2)


def test_retraction_revises_signal_without_duplicate_trade():
    withdrawal = Operation(
        "s1", "w1", "s1", T, T + timedelta(minutes=2), "retracted", (), True, "complete"
    )
    result = replay([swap("s1", "w1", T), withdrawal], [bar(T, "100")], T + timedelta(minutes=2))
    assert [r.decision.state for r in result.decisions] == ["candidate", "observing"]
    assert result.decisions[-1].decision.quality == "retracted"
