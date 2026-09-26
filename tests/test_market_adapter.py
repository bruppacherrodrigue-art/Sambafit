from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.market import GeckoClient, parse_candles, select_exact_pool
from rotation.pilot import PilotBudget

JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
T = datetime(2026, 9, 26, 6, 30, tzinfo=timezone.utc)


def pool(address, base, quote, reserve):
    return {
        "attributes": {
            "address": address,
            "reserve_in_usd": reserve,
            "base_token_price_usd": "0.34",
            "quote_token_price_usd": "120",
            "volume_usd": {"h24": "1000"},
        },
        "relationships": {
            "base_token": {"data": {"id": f"solana_{base}"}},
            "quote_token": {"data": {"id": f"solana_{quote}"}},
        },
    }


def test_exact_pool_selection_ignores_wrong_mint_and_uses_reserve_tiebreak():
    entries = [
        pool("wrong", JUP, USDC, "999999"),
        pool("z", JUP, WSOL, "200"),
        pool("a", WSOL, JUP, "200"),
    ]
    chosen = select_exact_pool(entries, JUP, WSOL)
    assert chosen.address == "a" and chosen.reserve_usd == Decimal("200")
    assert chosen.base_mint == WSOL and chosen.quote_mint == JUP


def test_candles_are_decimal_closed_intervals_and_do_not_inherit_spot_liquidity():
    payload = {
        "data": {
            "attributes": {
                "ohlcv_list": [
                    [1790404020, "0.34", "0.35", "0.33", "0.345", "99.5"],
                    [1790403960, "0.33", "0.34", "0.32", "0.34", "70"],
                ]
            }
        }
    }
    candles = parse_candles(payload, "pool", JUP, T - timedelta(minutes=2, seconds=30), seconds=60)
    assert len(candles) == 1
    assert candles[0].close_at.isoformat() == "2026-09-26T06:27:00+00:00"
    assert candles[0].close_usd == Decimal("0.34")
    assert candles[0].volume_usd == Decimal("70")
    assert candles[0].liquidity_usd is None


def test_client_reserves_before_http_and_rejects_rate_limit(tmp_path):
    class Response:
        status_code = 429
        text = '{"errors":[{"detail":"rate limited"}]}'

    class Client:
        def get(self, url, **kwargs):
            assert url.endswith("/networks/solana/tokens/" + JUP + "/pools")
            return Response()

    budget = PilotBudget(tmp_path / "budget.json", now=lambda: T)
    client = GeckoClient(budget, client=Client(), min_interval_seconds=0)
    try:
        client.token_pools(JUP)
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("429 must stop the pilot")
    assert budget.calls_used == 1
