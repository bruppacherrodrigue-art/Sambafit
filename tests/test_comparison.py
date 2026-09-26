from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.comparison import compare_variants
from rotation.engine import Rotation
from rotation.signals import MarketBar


def test_four_variants_run_on_same_synthetic_universe_and_capital():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        MarketBar(
            mint,
            start + timedelta(minutes=i),
            start + timedelta(minutes=i),
            Decimal(str(price)),
            Decimal("1000"),
            Decimal("100000"),
        )
        for i, price in enumerate((1, 2, 3, 4))
        for mint in ("A", "B")
    ]
    rotation = Rotation(
        "A",
        "B",
        "direct",
        "between_coins",
        Decimal("1000"),
        "wallet",
        "op",
        "op",
        start,
        start + timedelta(minutes=1),
    )
    result = compare_variants([rotation], bars, Decimal("1000"), {"A", "B"})
    assert set(result) == {"basket", "market_only", "wallets_only", "combined"}
    assert all(row["initial_cash"] == "1000" for row in result.values())
    assert all(row["period_start"] == start.isoformat() for row in result.values())
    assert all(
        row["period_end"] == (start + timedelta(minutes=3)).isoformat() for row in result.values()
    )
    assert result["basket"]["filled_orders"] >= 1


def test_realistic_missing_liquidity_blocks_all_variant_execution():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        MarketBar(
            "B",
            start + timedelta(minutes=i),
            start + timedelta(minutes=i),
            Decimal(i + 1),
            Decimal("100"),
            None,
        )
        for i in range(3)
    ]
    result = compare_variants([], bars, Decimal("1000"), {"B"})
    assert all(row["filled_orders"] == 0 for row in result.values())
    assert all(row["cash"] == "1000" for row in result.values())
    assert all(row["execution_status"] == "blocked_missing_liquidity" for row in result.values())
    assert all(row["net_return"] is None for row in result.values())
