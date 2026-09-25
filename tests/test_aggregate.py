from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Leg, Operation, aggregate_convergence, attribute_rotations
from rotation.signals import MarketBar, decide

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = Decimal


def op(name, wallet, kind, mint, delta):
    return Operation(
        name, wallet, name, T, T, kind, (Leg(mint, delta, 0, D("1")),), True, "complete"
    )


def test_aggregate_convergence_is_separate_from_inferred_transfer():
    operations = [
        op("sell", "seller", "sale", "A", -100),
        op("buy", "buyer", "buy", "B", 100),
        op("transfer", "x", "transfer", "A", -1000),
    ]
    assert attribute_rotations(operations) == []
    flows = aggregate_convergence(operations, T + timedelta(minutes=1))
    assert len(flows) == 1
    assert (flows[0].source, flows[0].destination, flows[0].amount_usd) == ("A", "B", D("100"))
    assert flows[0].seller_entities == 1 and flows[0].buyer_entities == 1
    assert flows[0].evidence == "aggregate" and flows[0].independence_uncertain is True


def test_linked_wallets_cannot_confirm_by_simulating_diversity():
    operations = [
        Operation(
            str(i),
            wallet,
            str(i),
            T,
            T,
            "swap",
            (Leg("A", -10000, 0, D("1")), Leg("B", 10000, 0, D("1"))),
            True,
            "complete",
        )
        for i, wallet in enumerate(("w1", "w2"))
    ]
    rotations = attribute_rotations(operations)
    bars = [MarketBar("B", T, T, D("1"), D("10000"), D("100000"))]
    independent = decide(rotations, bars, T)
    linked = decide(rotations, bars, T, entity_groups={"w1": "group1", "w2": "group1"})
    assert independent.state == "confirmed"
    assert linked.state == "candidate"
    assert dict(linked.components)["diversity"] == 8
