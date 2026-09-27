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


def pair_history():
    return [
        MarketBar(
            "A", T + timedelta(minutes=i), T + timedelta(minutes=i), D(a), D(100000), D(1000000)
        )
        for i, a in zip((-3, -2, -1, 0, 1, 2), ("5", "10", "9", "9", "9", "9"))
    ] + [
        bar(T + timedelta(minutes=i), b)
        for i, b in zip((-3, -2, -1, 0, 1, 2), ("10", "5", "5", "5.5", "5.6", "4"))
    ]


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
    bars = pair_history()
    result = replay(operations, bars, T + timedelta(minutes=2))
    assert [record.decision.state for record in result.decisions if record.at >= T] == [
        "candidate",
        "confirmed",
        "invalidated",
    ]
    assert result.decisions[-1].at == T + timedelta(minutes=2)


def test_retraction_revises_signal_without_duplicate_trade():
    withdrawal = Operation(
        "s1", "w1", "s1", T, T + timedelta(minutes=2), "retracted", (), True, "complete"
    )
    result = replay([swap("s1", "w1", T), withdrawal], pair_history(), T + timedelta(minutes=2))
    assert result.decisions[0].decision.state == "candidate"
    assert result.decisions[-1].decision.state == "invalidated"
    assert sum(r.decision.quality == "proof_removed" for r in result.decisions) == 1
    assert result.decisions[-1].decision.reasons == ("source_transaction_retracted",)


def test_same_signature_for_two_wallets_preserves_two_entities():
    a = swap("same", "w1", T)
    b = swap("same", "w2", T)
    result = replay([a, b], pair_history(), T)
    assert len(result.rotations) == 2
    assert result.decisions[-1].decision.state == "confirmed"
    assert result.aggregate_flows and result.aggregate_flows[0].evidence == "aggregate"


def test_future_watchlist_or_wallet_selection_cannot_retroactively_emit_signal():
    operations = [swap("s1", "w1", T)]
    bars = [bar(T, "100")]
    later = T + timedelta(days=1)
    assert replay(operations, bars, later, mint_known_at={"A": later}).rotations == ()
    assert replay(operations, bars, later, wallet_known_at={"w1": later}).rotations == ()
    assert (
        len(
            replay(
                operations, bars, later, mint_known_at={"A": T, "B": T}, wallet_known_at={"w1": T}
            ).rotations
        )
        == 1
    )
    assert replay(operations, bars, later, eligible_mints={"B"}).rotations == ()
    assert replay(operations, bars, later, eligible_wallets={"other"}).rotations == ()


def test_late_sale_cannot_emit_inferred_signal_before_sale_is_observed():
    sale = Operation(
        "sale",
        "w1",
        "sale",
        T,
        T + timedelta(minutes=10),
        "sale",
        (Leg("A", -100, 0, D("1")),),
        True,
        "complete",
    )
    buy = Operation(
        "buy",
        "w1",
        "buy",
        T + timedelta(minutes=1),
        T + timedelta(minutes=2),
        "buy",
        (Leg("B", 100, 0, D("1")),),
        True,
        "complete",
    )
    bars = [bar(T + timedelta(minutes=10), "100")]
    before = replay([sale, buy], bars, T + timedelta(minutes=9))
    after = replay([sale, buy], bars, T + timedelta(minutes=10))
    assert before.rotations == () and before.decisions == ()
    assert len(after.rotations) == 1
    assert after.rotations[0].available_at == T + timedelta(minutes=10)
    assert after.decisions[0].at == T + timedelta(minutes=10)
