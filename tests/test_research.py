from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.engine import Leg, Operation
from rotation.replay import replay
from rotation.research import price_operations, study_events
from rotation.signals import MarketBar

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
D = Decimal


def bar(mint, minutes, price, available_minutes=None):
    at = T + timedelta(minutes=minutes)
    available = T + timedelta(
        minutes=available_minutes if available_minutes is not None else minutes
    )
    return MarketBar(mint, at, available, D(price), D("10000"), D("1000000"))


def test_historical_valuation_never_uses_future_close_or_current_price():
    operation = Operation(
        "x",
        "w",
        "x",
        T,
        T + timedelta(days=1),
        "swap",
        (Leg("A", -1_000_000, 6, None), Leg("B", 2_000_000, 6, None)),
        True,
        "complete",
    )
    bars = [bar("A", 0, "10"), bar("B", 0, "5"), bar("A", 60, "1000"), bar("B", 60, "1000")]
    priced = price_operations([operation], bars)[0]
    assert [leg.usd_price for leg in priced.legs] == [D("10"), D("5")]
    assert price_operations([operation], bars[2:])[0].legs[0].usd_price is None


def test_event_study_requires_distinct_episode_and_reports_relative_return():
    op = Operation(
        "x",
        "w",
        "x",
        T + timedelta(minutes=3),
        T + timedelta(minutes=3),
        "swap",
        (Leg("A", -100, 0, D("100")), Leg("B", 100, 0, D("100"))),
        True,
        "complete",
    )
    bars = [bar("A", i, p) for i, p in enumerate(("50", "100", "90", "90", "90", "90", "90"))] + [
        bar("B", i, p) for i, p in enumerate(("110", "95", "95", "100", "100", "110", "90"))
    ]
    result = replay([op], bars, T + timedelta(minutes=6))
    report = study_events(result, bars, horizons_minutes=(2, 3))
    assert report["distinct_episodes"] == 1
    assert report["horizons"]["2"]["mean_relative_return"] == "0.1"
    assert report["horizons"]["3"]["mean_relative_return"] == "-0.1"
    assert report["horizons"]["2"]["confidence_interval"] is None
