from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Rotation
from rotation.signals import MarketBar, decide, decide_pairs

T = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
D = Decimal


def bars(mint, prices, *, start=T, liquidity="20000", volume_kind="interval"):
    return [
        MarketBar(
            mint,
            start + timedelta(minutes=i),
            start + timedelta(minutes=i),
            D(str(price)),
            D("100") + i * 10,
            D(liquidity) if liquidity is not None else None,
            volume_kind=volume_kind,
        )
        for i, price in enumerate(prices)
    ]


def rotation(source, destination, wallet="w1", amount="1500"):
    return Rotation(
        source,
        destination,
        "inferred",
        "between_coins",
        D(amount),
        wallet,
        f"sell-{source}-{wallet}",
        f"buy-{destination}-{wallet}",
        T + timedelta(minutes=2),
        T + timedelta(minutes=3),
    )


def test_source_range_changes_pair_decision_with_destination_unchanged():
    evidence = [rotation("A", "B")]
    b = bars("B", [10, 5, 5, 5.5])
    good = decide(evidence, bars("A", [5, 10, 9, 9]) + b, T + timedelta(minutes=3), pair=("A", "B"))
    low_source = decide(
        evidence, bars("A", [10, 10, 9, 9]) + b, T + timedelta(minutes=3), pair=("A", "B")
    )
    assert good.state == "candidate"
    assert low_source.state == "observing"
    assert "source_not_high_in_range" in low_source.reasons


def test_relative_force_changes_pair_decision_with_same_final_prices_and_ranges():
    evidence = [rotation("A", "B")]
    a = bars("A", [5, 10, 9, 9])
    improving = decide(
        evidence, a + bars("B", [10, 5, 5, 5.5]), T + timedelta(minutes=3), pair=("A", "B")
    )
    weakening = decide(
        evidence, a + bars("B", [10, 5, 6.5, 5.5]), T + timedelta(minutes=3), pair=("A", "B")
    )
    assert improving.state == "candidate"
    assert weakening.state == "observing"
    assert "relative_force_not_improving" in weakening.reasons


def test_distinct_sources_and_multiple_pairs_are_never_merged():
    evidence = [rotation("A", "B", "w1"), rotation("C", "B", "w2")]
    market = bars("A", [5, 10, 9, 9]) + bars("C", [5, 10, 9, 9]) + bars("B", [10, 5, 5, 5.5])
    decisions = decide_pairs(
        evidence, market, T + timedelta(minutes=3), eligible_mints={"A", "B", "C"}
    )
    assert set(decisions) == {("A", "B"), ("C", "B")}
    assert {decision.state for decision in decisions.values()} == {"candidate"}
    assert decide(evidence, market, T + timedelta(minutes=3)).quality == "ambiguous_pair"


def test_reserve_platform_and_other_network_are_not_memecoin_endpoints():
    market = bars("A", [5, 10, 9, 9]) + bars("B", [10, 5, 5, 5.5])
    evidence = [rotation("A", "B"), rotation("USDC", "B"), rotation("A", "PUMP")]
    decisions = decide_pairs(evidence, market, T + timedelta(minutes=3), eligible_mints={"A", "B"})
    assert set(decisions) == {("A", "B")}


def test_pair_market_gaps_stale_prices_and_rolling_volume_are_explicit():
    evidence = [rotation("A", "B")]
    market = bars("A", [5, 10, 9, 9]) + bars("B", [10, 5, 5, 5.5])
    stale = decide(evidence, market, T + timedelta(hours=1), pair=("A", "B"))
    assert stale.quality == "stale"
    rolling = decide(
        evidence,
        bars("A", [5, 10, 9, 9], volume_kind="rolling_24h") + bars("B", [10, 5, 5, 5.5]),
        T + timedelta(minutes=3),
        pair=("A", "B"),
    )
    assert rolling.quality == "incomplete_market"
    gap = bars("B", [10, 5, 5, 5.5])
    gap[2] = MarketBar(
        "B", T + timedelta(minutes=20), T + timedelta(minutes=20), D("5"), D("100"), D("20000")
    )
    broken = decide(
        evidence, bars("A", [5, 10, 9, 9]) + gap, T + timedelta(minutes=3), pair=("A", "B")
    )
    assert broken.quality == "incomplete_market"
