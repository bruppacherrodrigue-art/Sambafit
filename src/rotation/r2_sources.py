"""Read-only, budgeted R2 HTTP calls with one archive per attempted request."""

import json
import os
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import httpx

from .r2_budget import R2BudgetExceeded, _R2Session


class R2SourceError(RuntimeError):
    pass


class R2Http:
    GECKO = "https://api.geckoterminal.com/api/v2"
    READ_RPC = {"getTransaction", "getSignaturesForAddress", "getAccountInfo"}

    def __init__(
        self,
        session: _R2Session,
        archive: str | Path,
        *,
        client: httpx.Client | None = None,
        rpc_url: str = "https://solana.publicnode.com",
        min_interval_seconds: float = 10.0,
    ):
        self.session = session
        self.archive = Path(archive)
        self.client = client or httpx.Client(timeout=20)
        self.rpc_url = rpc_url
        self.min_interval_seconds = min_interval_seconds
        self.last_call: dict[str, float] = {}

    def _call(self, source: str, label: str, method: str, url: str, **kwargs) -> tuple[dict, dict]:
        delay = self.min_interval_seconds - (time.monotonic() - self.last_call.get(source, 0))
        remaining = self.session.remaining_seconds()
        if delay > 0 and delay + 0.25 >= remaining:
            raise R2BudgetExceeded("deadline before rate-limit wait")
        if delay > 0:
            time.sleep(delay)
        remaining = self.session.remaining_seconds()
        if remaining <= 0.25:
            raise R2BudgetExceeded("deadline before external request")
        timeout = min(20.0, remaining - 0.25)
        number = self.session.reserve(source, label)
        self.last_call[source] = time.monotonic()
        self.archive.mkdir(parents=True, exist_ok=True)
        path = self.archive / f"attempt-{number:04d}.json"
        try:
            response = self.client.request(method, url, timeout=timeout, **kwargs)
            received_at = datetime.now(timezone.utc).isoformat()
            body = response.text
            response_hash = sha256(response.content).hexdigest()
            record = {
                "attempt": number,
                "source": source,
                "request": label,
                "received_at": received_at,
                "http_status": response.status_code,
                "response_hash": response_hash,
                "body": body,
            }
            _atomic_json(path, record)
            receipt = {
                "attempt": number,
                "received_at": received_at,
                "response_hash": response_hash,
                "archive": str(path),
            }
            self.session.complete(
                number, status=f"http_{response.status_code}", response_hash=response_hash
            )
            if response.status_code != 200:
                retry_after = response.headers.get("Retry-After")
                suffix = (
                    f"; retry_after={retry_after}"
                    if response.status_code == 429 and retry_after
                    else ""
                )
                raise R2SourceError(f"{source} HTTP {response.status_code}{suffix}")
            payload = json.loads(body)
            return payload, receipt
        except httpx.HTTPError as exc:
            _atomic_json(
                path,
                {
                    "attempt": number,
                    "source": source,
                    "request": label,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "error_type": type(exc).__name__,
                },
            )
            self.session.complete(number, status=f"transport_{type(exc).__name__}")
            raise R2SourceError(f"{source} transport {type(exc).__name__}") from exc

    def gecko(self, path: str, params: dict | None = None) -> tuple[dict, dict]:
        solana_search = path == "/search/pools" and (params or {}).get("network") == "solana"
        if not (path.startswith("/networks/solana/") or solana_search) or ".." in path:
            raise ValueError("GeckoTerminal Solana path required")
        label = "GET " + path + (" " + json.dumps(params, sort_keys=True) if params else "")
        return self._call(
            "gecko",
            label,
            "GET",
            self.GECKO + path,
            params=params,
            headers={"Accept": "application/json;version=20230203"},
        )

    def rpc(self, method: str, params: list) -> tuple[object, dict]:
        if method not in self.READ_RPC:
            raise ValueError("RPC method is not read-only allowlisted")
        signature = (
            params[0]
            if method in {"getTransaction", "getSignaturesForAddress", "getAccountInfo"}
            else ""
        )
        payload, receipt = self._call(
            "rpc",
            f"{method}:{signature}",
            "POST",
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        if "error" in payload:
            code = payload["error"].get("code", "unknown")
            self.session.complete(
                receipt["attempt"],
                status=f"rpc_error_{code}",
                response_hash=receipt["response_hash"],
            )
            raise R2SourceError(f"RPC error {code}")
        return payload.get("result"), receipt


def _atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)
