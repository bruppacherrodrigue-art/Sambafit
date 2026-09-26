"""Durable, replayable R2 exploratory attribution across process sessions."""

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

WINDOW = timedelta(hours=6)


class SequenceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
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
                if event["direction"] not in {"buy", "sell"} or Decimal(event["amount_usd"]) <= 0:
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
            if event["direction"] == "sell":
                pending[event["signature"]] = {
                    **event,
                    "remaining_usd": Decimal(event["amount_usd"]),
                }
                continue
            remaining = Decimal(event["amount_usd"])
            for source in pending.values():
                if remaining <= 0:
                    break
                if (
                    source["wallet"] != event["wallet"]
                    or source["reserve_mint"] != event["reserve_mint"]
                    or source["coin_mint"] == event["coin_mint"]
                    or source["remaining_usd"] <= 0
                ):
                    continue
                gap = datetime.fromisoformat(event["economic_at"]) - datetime.fromisoformat(
                    source["economic_at"]
                )
                if gap < timedelta(0) or gap > WINDOW:
                    continue
                amount = min(remaining, source["remaining_usd"])
                source["remaining_usd"] -= amount
                remaining -= amount
                allocations.append(
                    {
                        "id": f"{source['signature']}:{event['signature']}",
                        "source_signature": source["signature"],
                        "destination_signature": event["signature"],
                        "wallet": event["wallet"],
                        "source_mint": source["coin_mint"],
                        "destination_mint": event["coin_mint"],
                        "reserve_mint": event["reserve_mint"],
                        "amount_usd": str(amount),
                        "evidence": "inferred_via_reserve",
                        "economic_at": event["economic_at"],
                        "available_at": max(source["available_at"], event["available_at"]),
                        "warning": "fund_identity_unproven; exploratory_backfill; provider_usd_estimate",
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
                (sig, json.dumps({**e, "remaining_usd": str(e["remaining_usd"])}, sort_keys=True))
                for sig, e in pending.items()
                if e["remaining_usd"] > 0
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
