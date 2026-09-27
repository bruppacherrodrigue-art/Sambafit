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
        self.revisions: dict[str, list[dict]] = {}
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
        for revision in payload.get("classification_revisions", []):
            mint = revision.get("mint")
            if (
                mint not in self.by_mint
                or not revision.get("proof")
                or not revision.get("proof_at")
            ):
                raise ValueError("classification revision needs known mint and dated proof")
            if revision.get("status") not in {
                "research_candidate",
                "admitted",
                "excluded",
                "uncertain",
            }:
                raise ValueError("invalid revision status")
            for key in ("known_at", "effective_from", "proof_at"):
                datetime.fromisoformat(revision[key])
            if revision.get("network", "solana") != "solana":
                raise ValueError("revision network must be Solana")
            if revision.get("role", "target") not in {
                "target",
                "reserve",
                "transit",
                "out_of_scope",
            }:
                raise ValueError("invalid revision role")
            self.revisions.setdefault(mint, []).append(revision)
        for rows in self.revisions.values():
            rows.sort(key=lambda row: row["known_at"])

    @classmethod
    def load(cls, path: str | Path) -> "ResearchRegistry":
        return cls(json.loads(Path(path).read_text()))

    def knowledge_times(self) -> tuple[datetime, ...]:
        return tuple(
            sorted(
                {
                    max(
                        datetime.fromisoformat(row["known_at"]),
                        datetime.fromisoformat(row["proof_at"]),
                    )
                    for rows in self.revisions.values()
                    for row in rows
                }
            )
        )

    def records_at(self, at: datetime) -> dict[str, dict]:
        if at < datetime.fromisoformat(self.known_at):
            return {}
        records = {}
        for mint, base in self.by_mint.items():
            if datetime.fromisoformat(base["known_at"]) > at:
                continue
            row = base
            for revision in self.revisions.get(mint, []):
                if (
                    max(
                        datetime.fromisoformat(revision["known_at"]),
                        datetime.fromisoformat(revision["proof_at"]),
                    )
                    <= at
                ):
                    row = {**row, **revision}
            records[mint] = row
        return records

    def eligible_mints(self, at: datetime) -> set[str]:
        return {
            mint
            for mint, row in self.records_at(at).items()
            if row["category"] == "memecoin"
            and row["role"] == "target"
            and row["status"] in TARGET_STATUSES
            and datetime.fromisoformat(row["known_at"]) <= at
            and datetime.fromisoformat(row["effective_from"]) <= at
        }
