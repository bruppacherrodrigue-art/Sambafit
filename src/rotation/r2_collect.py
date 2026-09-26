"""Checkpointed R2 transaction retrieval from selected public trade references."""

import json
import os
import re
from hashlib import sha256
from pathlib import Path

from .r2_budget import R2BudgetExceeded
from .r2_sources import R2Http, R2SourceError

SIGNATURE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{64,100}\Z")


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def _archived(http: R2Http, signature: str):
    for path in sorted(http.archive.glob("attempt-*.json")):
        record = json.loads(path.read_text())
        if (
            record.get("request") != f"getTransaction:{signature}"
            or record.get("http_status") != 200
        ):
            continue
        payload = json.loads(record["body"])
        if "error" not in payload:
            return payload.get("result"), {
                "attempt": record.get("attempt"),
                "received_at": record["received_at"],
                "response_hash": record["response_hash"],
            }
    return None


def collect_selected_transactions(
    root: str | Path, http: R2Http, *, limit: int, retry_errors: bool = False
) -> dict:
    """A recovered archive or raw file is never fetched again under a new call number."""
    if not 1 <= limit <= 500:
        raise ValueError("transaction batch limit must be 1..500")
    root = Path(root)
    path = root / "tx-selection.json"
    manifest = json.loads(path.read_text())
    attempted = 0
    reason = None
    for row in manifest["records"]:
        if row["status"] in {"fetched", "unavailable"}:
            continue
        if row["status"] in {"error", "budget_blocked"} and not retry_errors:
            continue
        signature = row["signature"]
        if not SIGNATURE.fullmatch(signature):
            raise ValueError("invalid selected signature")
        raw_path = root / "raw" / f"{signature}.json"
        prior = _archived(http, signature)
        if raw_path.exists():
            tx = json.loads(raw_path.read_text())
            receipt = prior[1] if prior else {}
        elif prior:
            tx, receipt = prior
        else:
            if attempted >= limit:
                reason = "batch_limit"
                break
            try:
                tx, receipt = http.rpc(
                    "getTransaction",
                    [
                        signature,
                        {
                            "encoding": "jsonParsed",
                            "commitment": "finalized",
                            "maxSupportedTransactionVersion": 1,
                        },
                    ],
                )
                attempted += 1
            except (R2SourceError, R2BudgetExceeded) as exc:
                row["status"] = "budget_blocked" if isinstance(exc, R2BudgetExceeded) else "error"
                row["error"] = str(exc)
                _write(path, manifest)
                reason = str(exc)
                break
        if tx is None:
            row.update(status="unavailable", **receipt)
        else:
            if (tx.get("transaction") or {}).get("signatures", [None])[0] != signature:
                row["status"] = "error"
                row["error"] = "RPC signature mismatch"
                _write(path, manifest)
                reason = row["error"]
                break
            canonical = json.dumps(tx, sort_keys=True, separators=(",", ":"))
            if not raw_path.exists():
                _write(raw_path, tx)
            row.update(
                status="fetched",
                slot=tx.get("slot"),
                block_time=tx.get("blockTime"),
                version=tx.get("version"),
                raw_hash=sha256(canonical.encode()).hexdigest(),
                source_attempt=receipt.get("attempt"),
                response_hash=receipt.get("response_hash"),
                raw_received_at=receipt.get("received_at"),
            )
        _write(path, manifest)
    return {
        "rpc_attempts_this_batch": attempted,
        "fetched": sum(r["status"] == "fetched" for r in manifest["records"]),
        "unavailable": sum(r["status"] == "unavailable" for r in manifest["records"]),
        "remaining": sum(r["status"] == "pending" for r in manifest["records"]),
        "stop_reason": reason,
    }
