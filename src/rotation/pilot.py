"""Persistent, shared pilot limits. Reserve a request before sending it."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable


class BudgetExceeded(RuntimeError):
    pass


class PilotBudget:
    def __init__(
        self,
        path: str | Path,
        *,
        max_calls: int = 120,
        max_transactions: int = 90,
        max_minutes: int = 15,
        now: Callable[[], datetime] | None = None,
    ):
        if (
            not 1 <= max_calls <= 1000
            or not 1 <= max_transactions <= 500
            or not 1 <= max_minutes <= 30
        ):
            raise ValueError("pilot limits exceed authorization")
        self.path = Path(path)
        self.now = now or (lambda: datetime.now(timezone.utc))
        limits = {
            "max_calls": max_calls,
            "max_transactions": max_transactions,
            "max_minutes": max_minutes,
        }
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if self.state["limits"] != limits:
                raise ValueError("cannot change limits when resuming a pilot")
        else:
            self.state = {
                "started_at": self.now().isoformat(),
                "limits": limits,
                "calls_used": 0,
                "by_source": {},
                "signatures": [],
                "attempts": [],
            }
            self._save()

    @property
    def calls_used(self) -> int:
        return self.state["calls_used"]

    @property
    def unique_transactions(self) -> int:
        return len(self.state["signatures"])

    @property
    def by_source(self) -> dict[str, int]:
        return dict(self.state["by_source"])

    def reserve(self, source: str, signature: str | None = None) -> None:
        if os.getenv("ROTATION_KILL_SWITCH") == "1":
            raise BudgetExceeded("kill switch active")
        started = datetime.fromisoformat(self.state["started_at"])
        if self.now() - started >= timedelta(minutes=self.state["limits"]["max_minutes"]):
            raise BudgetExceeded("time limit reached")
        if self.calls_used >= self.state["limits"]["max_calls"]:
            raise BudgetExceeded("call limit reached")
        if signature and signature not in self.state["signatures"]:
            if self.unique_transactions >= self.state["limits"]["max_transactions"]:
                raise BudgetExceeded("transaction limit reached")
            self.state["signatures"].append(signature)
        self.state["calls_used"] += 1
        self.state["by_source"][source] = self.state["by_source"].get(source, 0) + 1
        self.state["attempts"].append(
            {"source": source, "signature": signature, "at": self.now().isoformat()}
        )
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.path)


def collect_corpus(references, rpc, output: str | Path) -> dict:
    """Fetch each trade signature once; persist each raw before advancing manifest."""
    from .solana import PARSER_VERSION

    root = Path(output)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    manifest = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "source": "GeckoTerminal trades + Solana finalized getTransaction",
            "parser_version": PARSER_VERSION,
            "records": [],
        }
    )
    # A null finalized response is a recorded result for this bounded run.
    # Retrying it requires a new, explicitly budgeted corpus.
    known = {row["signature"] for row in manifest["records"]}
    for ref in references:
        signature = ref.signature
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{64,100}", signature):
            raise ValueError("invalid transaction signature")
        if signature in known:
            continue
        raw_path = raw_dir / f"{signature}.json"
        tx = (
            json.loads(raw_path.read_text(encoding="utf-8"))
            if raw_path.exists()
            else rpc.transaction(signature)
        )
        if tx is None:
            manifest["records"].append(
                {"signature": signature, "status": "unavailable", "pool": ref.pool}
            )
            _write_manifest(path, manifest)
            continue
        canonical = json.dumps(tx, sort_keys=True, separators=(",", ":"), default=str)
        if not raw_path.exists():
            temp = raw_path.with_suffix(".json.tmp")
            temp.write_text(canonical, encoding="utf-8")
            os.replace(temp, raw_path)
        manifest["records"].append(
            {
                "signature": signature,
                "slot": tx.get("slot"),
                "block_time": tx.get("blockTime"),
                "version": tx.get("version"),
                "status": "fetched",
                "pool": ref.pool,
                "reference_kind": ref.kind,
                "reported_actor": ref.reported_actor,
                "reference_volume_usd": str(ref.volume_usd) if ref.volume_usd is not None else None,
                "source_hash": sha256(canonical.encode()).hexdigest(),
                "raw_received_at": (
                    datetime.fromtimestamp(raw_path.stat().st_mtime, timezone.utc).isoformat()
                    if raw_path.exists()
                    else datetime.now(timezone.utc).isoformat()
                ),
                "parser_version": PARSER_VERSION,
            }
        )
        known.add(signature)
        _write_manifest(path, manifest)
    return manifest


def _write_manifest(path: Path, manifest: dict) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)
