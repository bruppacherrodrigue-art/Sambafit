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
