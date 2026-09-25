from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.demo import scenario
from rotation.paper import simulate_paper
from rotation.replay import replay
from rotation.signals import MarketBar

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
