"""Versioned, mint-keyed research classification; no investment approval."""

import json
import re
from datetime import datetime
from pathlib import Path

ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")
TARGET_STATUSES = {"research_candidate", "admitted"}


class ResearchRegistry:
    def __init__(self, payload: dict):
        self.payload = payload
        self.known_at = payload["known_at"]
        self.version = payload["version"]
        datetime.fromisoformat(self.known_at)
        self.by_mint = {}
        self.by_symbol = {}
        for row in payload["records"]:
            if row.get("network") != "solana" or not ADDRESS.fullmatch(row.get("mint", "")):
                raise ValueError("Solana mint required")
            if not row.get("proof") or not row.get("proof_at"):
                raise ValueError("dated classification proof required")
            if row["mint"] in self.by_mint:
                raise ValueError("duplicate mint")
            if row["status"] not in {"research_candidate", "admitted", "excluded", "uncertain"}:
                raise ValueError("invalid classification status")
            if row["role"] not in {"target", "reserve", "transit", "out_of_scope"}:
                raise ValueError("invalid study role")
            for key in ("known_at", "effective_from", "proof_at"):
                datetime.fromisoformat(row[key])
            self.by_mint[row["mint"]] = row
            self.by_symbol[row["symbol"]] = row

    @classmethod
    def load(cls, path: str | Path) -> "ResearchRegistry":
        return cls(json.loads(Path(path).read_text()))

    def eligible_mints(self, at: datetime) -> set[str]:
        if at < datetime.fromisoformat(self.known_at):
            return set()
        return {
            mint
            for mint, row in self.by_mint.items()
            if row["category"] == "memecoin"
            and row["role"] == "target"
            and row["status"] in TARGET_STATUSES
            and datetime.fromisoformat(row["known_at"]) <= at
            and datetime.fromisoformat(row["effective_from"]) <= at
        }
