import json
from decimal import Decimal

from rotation.r2_sequences import SequenceStore


def event(signature, direction, coin, usd, at, wallet="wallet", reserve="wSOL"):
    return {
        "signature": signature,
        "wallet": wallet,
        "coin_mint": coin,
        "direction": direction,
        "reserve_mint": reserve,
        "amount_usd": str(usd),
        "economic_at": at,
        "available_at": "2026-09-26T12:00:00+00:00",
    }


def test_pending_sale_survives_restart_and_cannot_be_spent_twice(tmp_path):
    path = tmp_path / "sequences.sqlite"
    with SequenceStore(path) as store:
        assert store.add([event("s", "sell", "A", 100, "2026-09-26T08:00:00+00:00")]) == 1
        assert store.snapshot()["pending"][0]["remaining_usd"] == "100"
    with SequenceStore(path) as store:
        assert (
            store.add(
                [
                    event("b1", "buy", "B", 60, "2026-09-26T08:10:00+00:00"),
                    event("b2", "buy", "C", 70, "2026-09-26T08:20:00+00:00"),
                ]
            )
            == 2
        )
        state = store.snapshot()
        assert [Decimal(x["amount_usd"]) for x in state["allocations"]] == [
            Decimal(60),
            Decimal(40),
        ]
        assert sum(Decimal(x["amount_usd"]) for x in state["allocations"]) <= Decimal(100)
        assert store.add([event("b1", "buy", "B", 60, "2026-09-26T08:10:00+00:00")]) == 0
        assert store.snapshot() == state


def test_reserve_and_late_events_do_not_create_direct_coin_rotation(tmp_path):
    with SequenceStore(tmp_path / "x.sqlite") as store:
        store.add([event("b", "buy", "B", 30, "2026-09-26T08:00:00+00:00")])
        assert store.snapshot()["allocations"] == []
        store.add([event("s", "sell", "A", 50, "2026-09-26T08:10:00+00:00", reserve="USDC")])
        assert store.snapshot()["allocations"] == []
        store.add([event("b2", "buy", "B", 30, "2026-09-26T08:20:00+00:00", reserve="USDC")])
        assert store.snapshot()["allocations"][0]["evidence"] == "inferred_via_reserve"
        assert store.snapshot()["pending"][0]["remaining_usd"] == "20"


def test_conflicting_same_signature_is_rejected(tmp_path):
    with SequenceStore(tmp_path / "x.sqlite") as store:
        first = event("s", "sell", "A", 10, "2026-09-26T08:00:00+00:00")
        store.add([first])
        second = json.loads(json.dumps(first))
        second["amount_usd"] = "100"
        try:
            store.add([second])
        except ValueError:
            pass
        else:
            raise AssertionError("changed history accepted")


def test_fifo_buyback_consumes_sale_before_other_coin(tmp_path):
    with SequenceStore(tmp_path / "buyback.sqlite") as store:
        store.add(
            [
                event("sale", "sell", "A", 100, "2026-09-26T10:00:00+00:00"),
                event("buyback", "buy", "A", 100, "2026-09-26T10:01:00+00:00"),
                event("other", "buy", "B", 100, "2026-09-26T10:02:00+00:00"),
            ]
        )
        assert store.snapshot()["allocations"] == []
        assert store.snapshot()["pending"] == []


def test_fifo_partial_buyback_and_outside_universe_consumption(tmp_path):
    with SequenceStore(tmp_path / "partial.sqlite") as store:
        store.add(
            [
                event("sale", "sell", "A", 100, "2026-09-26T10:00:00+00:00"),
                event("buyback", "buy", "A", 40, "2026-09-26T10:01:00+00:00"),
                event("outside", "buy", "PLATFORM", 20, "2026-09-26T10:02:00+00:00"),
                event("other", "buy", "B", 100, "2026-09-26T10:03:00+00:00"),
            ]
        )
        assert {
            a["destination_mint"]: Decimal(a["amount_usd"])
            for a in store.snapshot()["allocations"]
        } == {"PLATFORM": Decimal(20), "B": Decimal(40)}
        assert store.snapshot()["pending"] == []


def test_reserve_base_units_survive_price_change_and_do_not_cross_mints(tmp_path):
    sale = event("s", "sell", "A", 100, "2026-09-26T10:00:00+00:00")
    sale.update(reserve_quantity_base="1000000000", reserve_decimals=9)
    other_reserve = event("different", "buy", "B", 100, "2026-09-26T10:01:00+00:00", reserve="USDC")
    other_reserve.update(reserve_quantity_base="1000000", reserve_decimals=6)
    buy = event("b", "buy", "B", 150, "2026-09-26T10:02:00+00:00")
    buy.update(reserve_quantity_base="1000000000", reserve_decimals=9)
    with SequenceStore(tmp_path / "units.sqlite", eligible_mints={"A", "B"}) as store:
        store.add([sale, other_reserve, buy])
        row = store.snapshot()["allocations"][0]
        assert row["reserve_quantity_base"] == "1000000000"
        assert row["sale_value_usd"] == "100"
        assert row["buy_value_usd"] == "150"
        assert row["valuation_method"] == "historical_source_values"
        assert store.snapshot()["pending"] == []


def test_out_of_universe_buy_consumes_quantity_without_creating_rotation(tmp_path):
    sale = event("s", "sell", "A", 100, "2026-09-26T10:00:00+00:00")
    outside = event("x", "buy", "PLATFORM", 60, "2026-09-26T10:01:00+00:00")
    buy = event("b", "buy", "B", 100, "2026-09-26T10:02:00+00:00")
    for item, qty in ((sale, 100), (outside, 60), (buy, 100)):
        item.update(reserve_quantity_base=str(qty), reserve_decimals=6)
    with SequenceStore(tmp_path / "scope.sqlite", eligible_mints={"A", "B"}) as store:
        store.add([sale, outside, buy])
        rows = store.snapshot()["allocations"]
        assert len(rows) == 1
        assert rows[0]["destination_mint"] == "B"
        assert rows[0]["reserve_quantity_base"] == "40"
