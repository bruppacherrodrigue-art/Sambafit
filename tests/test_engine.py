from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Leg, Operation, attribute_rotations
from rotation.paper import PaperBook
from rotation.signals import MarketBar, decide, market_features

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = Decimal


def op(name, kind, at, legs, wallet="w1", available=None, quality="complete", finalized=True):
    return Operation(name, wallet, name, at, available or at, kind, tuple(legs), finalized, quality)


def leg(mint, delta, price="1", decimals=0):
    return Leg(mint, delta, decimals, D(price) if price is not None else None)


def test_direct_routed_swap_is_one_economic_rotation():
    routed = op("tx1", "swap", T, [leg("A", -100), leg("SOL", 0), leg("B", 50, "2")])
    rotations = attribute_rotations([routed], stable_mints={"USDC"}, bridge_mints={"SOL"})
    assert [(r.source, r.destination, r.evidence, r.amount_usd) for r in rotations] == [
        ("A", "B", "direct", D("100"))
    ]


def test_inferred_split_conserves_sale_value_and_orders_by_availability():
    events = [
        op("sell", "sale", T, [leg("A", -100)]),
        op("buy-b", "buy", T + timedelta(minutes=1), [leg("B", 30, "2")]),
        op("buy-c", "buy", T + timedelta(minutes=2), [leg("C", 80)]),
    ]
    rotations = attribute_rotations(events, window=timedelta(hours=1))
    assert [(r.destination, r.amount_usd) for r in rotations] == [("B", D("60")), ("C", D("40"))]
    assert sum(r.amount_usd for r in rotations) == D("100")


def test_engine_fifo_buyback_consumes_sale_before_other_coin():
    events = [
        op("sale", "sale", T, [leg("A", -100)]),
        op("buyback", "buy", T + timedelta(minutes=1), [leg("A", 100)]),
        op("other", "buy", T + timedelta(minutes=2), [leg("B", 100)]),
    ]
    assert attribute_rotations(events) == []


def test_late_sale_pairs_by_economic_order_only_after_both_events_are_available():
    sale = op("sell", "sale", T, [leg("A", -100)], available=T + timedelta(minutes=10))
    buy = op(
        "buy",
        "buy",
        T + timedelta(minutes=1),
        [leg("B", 100)],
        available=T + timedelta(minutes=2),
    )
    assert attribute_rotations([buy]) == []
    rotations = attribute_rotations([buy, sale])
    assert len(rotations) == 1
    assert rotations[0].evidence == "inferred"
    assert rotations[0].economic_at == buy.economic_at
    assert rotations[0].available_at == sale.available_at


def test_nontrades_failed_partial_and_unpriced_do_not_rotate():
    kinds = ("transfer", "wrap", "airdrop", "lp_add", "lp_remove", "unknown")
    events = [op(str(i), kind, T, [leg("A", -100), leg("B", 100)]) for i, kind in enumerate(kinds)]
    events += [op("failed", "swap", T, [leg("A", -100), leg("B", 100)], finalized=False)]
    events += [op("partial", "swap", T, [leg("A", -100), leg("B", 100)], quality="partial")]
    events += [op("unpriced", "swap", T, [leg("A", -100, None), leg("B", 100)])]
    rotations = attribute_rotations(events)
    assert len(rotations) == 1 and rotations[0].source_op == "unpriced"
    assert rotations[0].amount_usd is None


def test_direct_swap_does_not_create_inferred_pair():
    events = [
        op("direct", "swap", T, [leg("A", -100), leg("B", 100)]),
        op("buy", "buy", T + timedelta(minutes=1), [leg("C", 100)]),
    ]
    rotations = attribute_rotations(events)
    assert len(rotations) == 1 and rotations[0].evidence == "direct"


def test_stable_exit_has_no_fictitious_destination_coin():
    rotations = attribute_rotations(
        [op("exit", "swap", T, [leg("A", -100), leg("USDC", 100)])], stable_mints={"USDC"}
    )
    assert len(rotations) == 1
    assert rotations[0].destination == "USDC" and rotations[0].direction == "to_stable"


def test_usdc_and_sol_entries_are_not_between_coin_rotations():
    events = [
        op("stable-entry", "swap", T, [leg("USDC", -100), leg("JUP", 100)]),
        op("sol-entry", "swap", T, [leg("SOL", -100), leg("JUP", 100)]),
    ]
    rotations = attribute_rotations(events, stable_mints={"USDC"}, reserve_mints={"SOL"})
    assert {r.direction for r in rotations} == {"from_stable", "from_reserve"}


def test_market_features_exclude_future_and_unclosed_bars():
    bars = [
        MarketBar(
            "B",
            T + timedelta(minutes=i),
            T + timedelta(minutes=i),
            D(str(i + 1)),
            D("100"),
            D("1000"),
        )
        for i in range(3)
    ]
    bars.append(
        MarketBar(
            "B", T + timedelta(minutes=4), T + timedelta(minutes=4), D("100"), D("100"), D("1000")
        )
    )
    features = market_features(bars, "B", T + timedelta(minutes=2), lookback=3)
    assert features.last_price == D("3")
    assert features.range_position == D("1")


def test_sparse_minute_bars_do_not_claim_volume_acceleration():
    bars = [
        MarketBar("B", T, T, D("1"), D("100"), None),
        MarketBar(
            "B", T + timedelta(minutes=10), T + timedelta(minutes=10), D("2"), D("200"), None
        ),
    ]
    assert market_features(bars, "B", T + timedelta(minutes=10)).volume_acceleration is None


def test_stale_market_blocks_decision_and_future_data_cannot_change_past_decision():
    rotation = attribute_rotations([op("direct", "swap", T, [leg("A", -100), leg("B", 100)])])[0]
    bars = [MarketBar("B", T, T, D("1"), D("100"), D("1000"))]
    before = decide([rotation], bars, T + timedelta(minutes=1), max_age=timedelta(minutes=5))
    with_future = decide(
        [rotation],
        bars
        + [
            MarketBar(
                "B", T + timedelta(hours=1), T + timedelta(hours=1), D("1000"), D("1"), D("1")
            )
        ],
        T + timedelta(minutes=1),
        max_age=timedelta(minutes=5),
    )
    stale = decide([rotation], bars, T + timedelta(hours=1), max_age=timedelta(minutes=5))
    assert before == with_future
    assert stale.state == "observing" and stale.quality == "stale"


def test_old_market_bar_imported_now_stays_stale():
    rotation = attribute_rotations([op("direct", "swap", T, [leg("A", -100), leg("B", 100)])])[0]
    decision_at = T + timedelta(hours=2)
    late_import = [MarketBar("B", T, decision_at, D("1"), D("100"), D("100000"))]
    decision = decide([rotation], late_import, decision_at, max_age=timedelta(minutes=5))
    assert decision.state == "observing" and decision.quality == "stale"


def test_paper_sale_filled_buy_failed_keeps_cash_and_no_fake_position():
    book = PaperBook(cash=D("0"), positions={"A": D("10")})
    book.sell("A", D("10"), D("10"), D("1"), "sell-1")
    book.buy("B", D("50"), D("2"), D("1"), "buy-1", executable=False)
    assert book.cash == D("99") and book.positions == {}
    book.sell("A", D("10"), D("10"), D("1"), "sell-1")
    assert book.cash == D("99")
