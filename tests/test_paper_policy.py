from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.demo import scenario
from rotation.paper import simulate_paper
from rotation.replay import DecisionRecord, replay
from rotation.signals import Decision, MarketBar

D = Decimal
T = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_confirmed_demo_enters_next_bar_and_exits_after_invalidation():
    operations, bars = scenario()
    result = replay(operations, bars, T + timedelta(minutes=4))
    simulation = simulate_paper(
        result.decisions,
        bars,
        D("1000"),
        allocation_fraction=D("0.25"),
        fee_rate=D("0.005"),
        impact_rate=D("0.005"),
        network_fee=D("0.01"),
    )
    assert [o["side"] for o in simulation.orders if o["status"] == "filled"] == ["buy", "sell"]
    assert simulation.book.positions == {}
    assert simulation.book.cash < D("1000")
    assert simulation.orders[0]["at"] > result.decisions[1].at


def test_missing_liquidity_rejects_entry_without_spending_cash():
    operations, bars = scenario()
    dry = [
        MarketBar(b.mint, b.close_at, b.available_at, b.close_usd, b.volume_usd, None) for b in bars
    ]
    result = replay(operations, dry, T + timedelta(minutes=4))
    simulation = simulate_paper(result.decisions, dry, D("1000"))
    assert simulation.book.cash == D("1000") and simulation.book.positions == {}
    assert not [o for o in simulation.orders if o["status"] == "filled"]


def test_paper_fills_follow_quote_time_not_signal_list_order():
    confirmed = Decision("confirmed", "complete", 60, (), ())
    records = (
        DecisionRecord(T, "X:A", confirmed),
        DecisionRecord(T + timedelta(minutes=1), "X:B", confirmed),
    )
    bars = [
        MarketBar(
            "B",
            T + timedelta(minutes=2),
            T + timedelta(minutes=2),
            D("1"),
            D("10000"),
            D("1000000"),
        ),
        MarketBar(
            "A",
            T + timedelta(minutes=10),
            T + timedelta(minutes=10),
            D("1"),
            D("10000"),
            D("1000000"),
        ),
    ]
    result = simulate_paper(
        records,
        bars,
        D("1000"),
        allocation_fraction=D("0.5"),
        fee_rate=D("0"),
        impact_rate=D("0"),
        network_fee=D("0"),
    )
    assert [order["mint"] for order in result.orders] == ["B", "A"]
    assert result.book.positions == {"B": D("500"), "A": D("250")}


def test_stale_existing_position_mark_blocks_second_entry():
    confirmed = Decision("confirmed", "complete", 60, (), ())
    records = (
        DecisionRecord(T, "X:A", confirmed),
        DecisionRecord(T + timedelta(minutes=1), "X:B", confirmed),
    )
    bars = [
        MarketBar(
            "A",
            T + timedelta(minutes=1),
            T + timedelta(minutes=1),
            D("1"),
            D("10000"),
            D("1000000"),
        ),
        MarketBar(
            "B",
            T + timedelta(minutes=40),
            T + timedelta(minutes=40),
            D("1"),
            D("10000"),
            D("1000000"),
        ),
    ]
    result = simulate_paper(
        records, bars, D("1000"), fee_rate=D(0), impact_rate=D(0), network_fee=D(0)
    )
    assert [o["status"] for o in result.orders] == ["filled", "unfilled"]
    assert result.orders[1]["reason"] == "missing or stale position mark"
    assert result.book.positions == {"A": D("250")}
