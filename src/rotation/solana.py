"""Bounded finalized Solana RPC reader and conservative balance decoder."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .engine import Leg, Operation

PARSER_VERSION = "solana-balances-1"


class RpcError(RuntimeError):
    pass


class SolanaRpc:
    def __init__(
        self, url: str, client=None, max_calls: int = 100, min_interval_seconds: float = 0.2
    ):
        self.url = url
        self.client = client or httpx.Client(timeout=10)
        self.max_calls = max_calls
        self.min_interval_seconds = min_interval_seconds
        self.calls = 0
        self.last_call = 0.0

    def call(self, method: str, params: list):
        if method not in {"getSignaturesForAddress", "getTransaction", "getTokenAccountsByOwner"}:
            raise RpcError("RPC method not allowlisted")
        if self.calls >= self.max_calls:
            raise RpcError("RPC call budget exhausted")
        delay = self.min_interval_seconds - (time.monotonic() - self.last_call)
        if delay > 0:
            time.sleep(delay)
        self.calls += 1
        self.last_call = time.monotonic()
        try:
            response = self.client.post(
                self.url,
                json={"jsonrpc": "2.0", "id": self.calls, "method": method, "params": params},
            )
            if response.status_code != 200:
                raise RpcError(f"RPC HTTP {response.status_code}")
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RpcError(f"RPC transport: {type(exc).__name__}") from exc
        if "error" in payload:
            raise RpcError(f"RPC error {payload['error'].get('code', 'unknown')}")
        return payload.get("result")

    def signatures(self, address: str, limit: int = 20, before: str | None = None):
        if limit < 1 or limit > 1000:
            raise ValueError("signature page size must be 1..1000")
        options = {"limit": limit, "commitment": "finalized"}
        if before:
            options["before"] = before
        return self.call("getSignaturesForAddress", [address, options])

    def transaction(self, signature: str):
        return self.call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": "finalized",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )

    def token_accounts(self, owner: str, program_id: str):
        return self.call(
            "getTokenAccountsByOwner",
            [
                owner,
                {"programId": program_id},
                {"encoding": "jsonParsed", "commitment": "finalized"},
            ],
        )


@dataclass(frozen=True)
class DecodedTx:
    operation: Operation
    fee_lamports: int
    parser_version: str = PARSER_VERSION


class SolanaDecoder:
    def __init__(self, swap_program_ids: set[str]):
        self.swap_program_ids = swap_program_ids

    def decode(self, tx: dict, wallet: str, available_at: datetime) -> DecodedTx:
        meta = tx.get("meta") or {}
        message = (tx.get("transaction") or {}).get("message") or {}
        signature = next(
            iter((tx.get("transaction") or {}).get("signatures") or []),
            f"missing-{tx.get('slot', 0)}",
        )
        version = tx.get("version", "legacy")
        block_time = tx.get("blockTime")
        economic_at = (
            datetime.fromtimestamp(block_time, timezone.utc)
            if block_time is not None
            else available_at
        )
        pre = self._balances(meta.get("preTokenBalances") or [], wallet)
        post = self._balances(meta.get("postTokenBalances") or [], wallet)
        legs = tuple(
            Leg(mint, post.get(mint, (0, dec))[0] - pre.get(mint, (0, dec))[0], dec, None)
            for mint in sorted(pre.keys() | post.keys())
            for dec in [(post.get(mint) or pre[mint])[1]]
            if post.get(mint, (0, dec))[0] != pre.get(mint, (0, dec))[0]
        )
        if version not in ("legacy", 0):
            quality, kind = "unsupported_version", "unknown"
        elif not meta or block_time is None:
            quality, kind = "partial", "unknown"
        elif meta.get("err") is not None:
            quality, kind = "complete", "failed"
        else:
            instructions = list(message.get("instructions") or [])
            for group in meta.get("innerInstructions") or []:
                instructions.extend(group.get("instructions") or [])
            programs = {i.get("programId") for i in instructions}
            types = {
                (i.get("parsed") or {}).get("type")
                for i in instructions
                if isinstance(i.get("parsed"), dict)
            }
            neg = [leg for leg in legs if leg.delta_base < 0]
            pos = [leg for leg in legs if leg.delta_base > 0]
            if "syncNative" in types or "closeAccount" in types:
                quality, kind = "complete", "wrap"
            elif "deposit" in types or "withdraw" in types:
                quality, kind = "complete", "lp_add" if "deposit" in types else "lp_remove"
            elif programs & self.swap_program_ids and len(neg) == 1 and len(pos) == 1:
                quality, kind = "complete", "swap"
            elif types & {"transfer", "transferChecked"} and len(legs) <= 1:
                quality, kind = "complete", "transfer"
            else:
                quality, kind = "partial", "unknown"
        return DecodedTx(
            Operation(
                signature, wallet, signature, economic_at, available_at, kind, legs, True, quality
            ),
            int(meta.get("fee") or 0),
        )

    @staticmethod
    def _balances(entries: list[dict], wallet: str) -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        for item in entries:
            if item.get("owner") != wallet:
                continue
            mint = item["mint"]
            amount = item["uiTokenAmount"]
            base, decimals = int(amount["amount"]), int(amount["decimals"])
            previous, old_decimals = result.get(mint, (0, decimals))
            if decimals != old_decimals:
                raise ValueError("inconsistent token decimals")
            result[mint] = (previous + base, decimals)
        return result
