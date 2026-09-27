import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from rotation.engine import Leg, Operation, Rotation
from rotation.r2_follow import refresh_follow_state
from rotation.replay import replay
from rotation.signals import MarketBar, decide

T = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
D = Decimal


def market(mint: str, prices: list[str]) -> list[MarketBar]:
    return [
        MarketBar(
            mint,
            T + timedelta(minutes=i),
            T + timedelta(minutes=i),
            D(price),
            D(100 + i),
            D(20000),
        )
        for i, price in enumerate(prices)
    ]


def swap(
    name: str, source: str, destination: str, economic: datetime, available: datetime
) -> Operation:
    source_amount = 1500 if source == "R" else 100
    destination_amount = 1500 if destination == "R" else 100
    return Operation(
        name,
        "wallet",
        name,
        economic,
        available,
        "swap",
        (
            Leg(source, -source_amount, 0, D(1) if source == "R" else D(15)),
            Leg(destination, destination_amount, 0, D(1) if destination == "R" else D(15)),
        ),
        True,
        "complete",
    )


def test_t1_old_economic_flow_received_now_cannot_be_candidate():
    late = Rotation(
        "A",
        "B",
        "inferred",
        "between_coins",
        D(1500),
        "wallet",
        "sale",
        "buy",
        T - timedelta(days=7),
        T + timedelta(minutes=3),
    )
    decision = decide(
        [late],
        market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"]),
        T + timedelta(minutes=3),
        pair=("A", "B"),
    )
    assert decision.state != "candidate"
    assert "economic_flow_stale" in decision.reasons


def test_t2_late_buyback_cancels_previously_known_pair_without_rewriting_it():
    bars = market("A", ["5", "10", "9", "9"]) + market("B", ["10", "5", "5", "5.5"])
    sale = swap("sale", "A", "R", T, T)
    buy_b = swap("buy-b", "R", "B", T + timedelta(minutes=2), T + timedelta(minutes=3))
    buyback = swap("buyback", "R", "A", T + timedelta(minutes=1), T + timedelta(minutes=4))
    before = replay(
        [sale, buy_b],
        bars,
        T + timedelta(minutes=3),
        reserve_mints={"R"},
        eligible_mints={"A", "B"},
    )
    assert [(row.pair, row.decision.state) for row in before.decisions] == [("A:B", "candidate")]
    after = replay(
        [sale, buy_b, buyback],
        bars,
        T + timedelta(minutes=4),
        reserve_mints={"R"},
        eligible_mints={"A", "B"},
    )
    assert after.decisions[: len(before.decisions)] == before.decisions
    assert after.rotations == ()
    assert [(row.at, row.pair, row.decision.state) for row in after.decisions[-1:]] == [
        (T + timedelta(minutes=4), "A:B", "invalidated")
    ]


def test_t3_reddecode_cannot_reuse_old_raw_receipt_as_new_proof_time(tmp_path):
    corpus = Path("data/r3-20260927")
    selected = json.loads((corpus / "preselection.json").read_text())["references"]
    row = next(item for item in selected if item["attribution_status"] == "verified_swap")
    signature = row["signature"]
    old_receipt = datetime(2026, 9, 25, tzinfo=timezone.utc)
    root = tmp_path
    (root / "follow-raw").mkdir()
    (root / "follow-raw" / f"{signature}.json").write_bytes(
        (corpus / "raw" / f"{signature}.json").read_bytes()
    )
    (root / "follow-checkpoint.json").write_text(
        json.dumps(
            {
                "started_at": old_receipt.isoformat(),
                "wallets": {row["owner_wallet"]: {}},
                "transactions": {
                    signature: {
                        "status": "fetched",
                        "wallet": row["owner_wallet"],
                        "kind": "unknown",
                        "quality": "partial",
                        "legs": [],
                        "economic_at": row["block_at"],
                        "receipt": {
                            "received_at": old_receipt.isoformat(),
                            "attempt": 1,
                            "response_hash": "raw",
                        },
                    }
                },
                "enrichment_queue": [{"signature": signature, "reason": "partial"}],
            }
        )
    )
    refreshed = refresh_follow_state(root)
    revised = refreshed["transactions"][signature]
    assert revised["kind"] == "swap" and revised["quality"] == "complete"
    assert datetime.fromisoformat(revised["effective_available_at"]) > old_receipt
    assert len(revised["decode_revisions"]) == 2
