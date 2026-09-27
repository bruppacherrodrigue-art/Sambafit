"""Durable, replayable R2 exploratory attribution across process sessions."""

import json
import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from .reserve_fifo import consume

WINDOW = timedelta(hours=6)


class SequenceStore:
    def __init__(self, path: str | Path, eligible_mints: set[str] | None = None):
        self.path = Path(path)
        self.eligible_mints = eligible_mints
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events(signature TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS allocations(id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS pending(signature TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def add(self, events: list[dict]) -> int:
        count = 0
        with self.db:
            for event in events:
                amount = event.get("reserve_quantity_base", event.get("amount_usd"))
                if event["direction"] not in {"buy", "sell"} or amount is None or Decimal(amount) <= 0:
                    raise ValueError("invalid directional event")
                canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
                prior = self.db.execute(
                    "SELECT payload FROM events WHERE signature=?", (event["signature"],)
                ).fetchone()
                if prior:
                    if prior[0] != canonical:
                        raise ValueError("conflicting event for signature")
                    continue
                self.db.execute("INSERT INTO events VALUES (?,?)", (event["signature"], canonical))
                count += 1
            self._rebuild()
        return count

    def _rebuild(self):
        rows = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM events")]
        rows.sort(key=lambda e: (e["economic_at"], e["signature"]))
        pending: dict[str, dict] = {}
        allocations = []
        for event in rows:
            base = event.get("reserve_quantity_base")
            unit = "reserve_base" if base is not None else "usd_proxy"
            amount = Decimal(base if base is not None else event["amount_usd"])
            if event["direction"] == "sell":
                pending[event["signature"]] = {
                    **event,
                    "amount": amount,
                    "remaining": amount,
                    "unit": unit,
                    "reserve_decimals": int(event.get("reserve_decimals", 0)),
                    "remaining_usd": amount if unit == "usd_proxy" else None,
                }
                continue
            debit = {
                **event,
                "amount": amount,
                "unit": unit,
                "reserve_decimals": int(event.get("reserve_decimals", 0)),
            }
            for source, matched in consume(list(pending.values()), debit, WINDOW):
                if source["coin_mint"] == event["coin_mint"]:
                    continue
                if self.eligible_mints is not None and (
                    source["coin_mint"] not in self.eligible_mints
                    or event["coin_mint"] not in self.eligible_mints
                ):
                    continue
                source_value = (
                    Decimal(source["amount_usd"]) * matched / source["amount"]
                    if source.get("amount_usd") is not None
                    else None
                )
                destination_value = (
                    Decimal(event["amount_usd"]) * matched / amount
                    if event.get("amount_usd") is not None
                    else None
                )
                allocations.append(
                    {
                        "id": f"{source['signature']}:{event['signature']}",
                        "source_signature": source["signature"],
                        "destination_signature": event["signature"],
                        "wallet": event["wallet"],
                        "source_mint": source["coin_mint"],
                        "destination_mint": event["coin_mint"],
                        "reserve_mint": event["reserve_mint"],
                        "amount_usd": str(min(source_value, destination_value))
                        if source_value is not None and destination_value is not None
                        else None,
                        "reserve_quantity_base": str(matched) if unit == "reserve_base" else None,
                        "reserve_decimals": debit["reserve_decimals"] if unit == "reserve_base" else None,
                        "sale_value_usd": str(source_value) if source_value is not None else None,
                        "buy_value_usd": str(destination_value) if destination_value is not None else None,
                        "valuation_method": "historical_source_values" if unit == "reserve_base" else "legacy_usd_proxy",
                        "evidence": "inferred_via_reserve",
                        "economic_at": event["economic_at"],
                        "available_at": max(source["available_at"], event["available_at"]),
                        "warning": "fund_identity_unproven; exploratory_backfill; "
                        + ("reserve_base_conserved" if unit == "reserve_base" else "legacy_usd_proxy"),
                    }
                )
        self.db.execute("DELETE FROM allocations")
        self.db.executemany(
            "INSERT INTO allocations VALUES (?,?)",
            [(a["id"], json.dumps(a, sort_keys=True)) for a in allocations],
        )
        self.db.execute("DELETE FROM pending")
        self.db.executemany(
            "INSERT INTO pending VALUES (?,?)",
            [
                (
                    sig,
                    json.dumps(
                        {
                            **e,
                            "amount": str(e["amount"]),
                            "remaining": str(e["remaining"]),
                            "remaining_usd": str(e["remaining"])
                            if e["unit"] == "usd_proxy"
                            else None,
                        },
                        sort_keys=True,
                    ),
                )
                for sig, e in pending.items()
                if e["remaining"] > 0
            ],
        )

    def snapshot(self) -> dict:
        return {
            "event_count": self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "allocations": [
                json.loads(row[0])
                for row in self.db.execute("SELECT payload FROM allocations ORDER BY id")
            ],
            "pending": [
                json.loads(row[0])
                for row in self.db.execute("SELECT payload FROM pending ORDER BY signature")
            ],
            "coverage": "sampled_swaps_only; opening_positions_unknown",
            "window_seconds": int(WINDOW.total_seconds()),
        }
