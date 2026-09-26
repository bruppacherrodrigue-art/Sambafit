"""Read-only GeckoTerminal adapter; spot snapshots and OHLCV remain distinct."""

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from .pilot import PilotBudget

BASE_URL = "https://api.geckoterminal.com/api/v2"
API_VERSION = "20230203"
ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")


class MarketSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PoolInfo:
    address: str
    base_mint: str
    quote_mint: str
    reserve_usd: Decimal | None
    base_price_usd: Decimal | None
    quote_price_usd: Decimal | None
    volume_h24_usd: Decimal | None
    received_at: datetime


@dataclass(frozen=True)
class TradeRef:
    signature: str
    slot: int
    block_at: datetime
    reported_actor: str | None
    kind: str
    from_mint: str
    to_mint: str
    from_amount: Decimal
    to_amount: Decimal
    volume_usd: Decimal | None
    pool: str


@dataclass(frozen=True)
class HistoricalCandle:
    mint: str
    pool: str
    interval_start: datetime
    close_at: datetime
    received_at: datetime
    close_usd: Decimal
    volume_usd: Decimal
    liquidity_usd: None = None


def _decimal(value) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _mint_id(entry: dict, role: str) -> str:
    identifier = entry["relationships"][role]["data"]["id"]
    if not identifier.startswith("solana_"):
        raise ValueError("pool token network is not Solana")
    return identifier.removeprefix("solana_")


def parse_pool(entry: dict, received_at: datetime) -> PoolInfo:
    attrs = entry["attributes"]
    return PoolInfo(
        attrs["address"],
        _mint_id(entry, "base_token"),
        _mint_id(entry, "quote_token"),
        _decimal(attrs.get("reserve_in_usd")),
        _decimal(attrs.get("base_token_price_usd")),
        _decimal(attrs.get("quote_token_price_usd")),
        _decimal((attrs.get("volume_usd") or {}).get("h24")),
        received_at,
    )


def select_exact_pool(
    entries: list[dict], mint_a: str, mint_b: str, received_at: datetime | None = None
) -> PoolInfo:
    received_at = received_at or datetime.now(timezone.utc)
    candidates = [parse_pool(item, received_at) for item in entries]
    matches = [item for item in candidates if {item.base_mint, item.quote_mint} == {mint_a, mint_b}]
    if not matches:
        raise ValueError("no exact pool for technical pair")
    return sorted(matches, key=lambda item: (-(item.reserve_usd or Decimal(0)), item.address))[0]


def parse_candles(
    payload: dict, pool: str, mint: str, received_at: datetime, seconds: int = 60
) -> list[HistoricalCandle]:
    if seconds < 1:
        raise ValueError("invalid candle interval")
    results = []
    for item in payload["data"]["attributes"]["ohlcv_list"]:
        start = datetime.fromtimestamp(int(item[0]), timezone.utc)
        end = start + timedelta(seconds=seconds)
        if end > received_at:
            continue  # A still-open candle cannot enter a decision.
        close, volume = _decimal(item[4]), _decimal(item[5])
        if close is None or volume is None or close <= 0 or volume < 0:
            continue
        results.append(HistoricalCandle(mint, pool, start, end, received_at, close, volume))
    return sorted(results, key=lambda candle: candle.close_at)


def parse_trades(payload: dict, pool: str) -> list[TradeRef]:
    trades = []
    for item in payload.get("data", []):
        attrs = item["attributes"]
        trades.append(
            TradeRef(
                attrs["tx_hash"],
                int(attrs["block_number"]),
                datetime.fromisoformat(attrs["block_timestamp"].replace("Z", "+00:00")),
                attrs.get("tx_from_address"),
                attrs["kind"],
                attrs["from_token_address"],
                attrs["to_token_address"],
                Decimal(attrs["from_token_amount"]),
                Decimal(attrs["to_token_amount"]),
                _decimal(attrs.get("volume_in_usd")),
                pool,
            )
        )
    return trades


class GeckoClient:
    def __init__(self, budget: PilotBudget, *, client=None, min_interval_seconds: float = 10.0):
        self.budget = budget
        self.client = client or httpx.Client(timeout=20)
        self.min_interval_seconds = min_interval_seconds
        self.last_call = 0.0

    def _get(self, path: str, params: dict | None = None) -> dict:
        delay = self.min_interval_seconds - (time.monotonic() - self.last_call)
        if delay > 0:
            time.sleep(delay)
        self.budget.reserve("gecko")
        self.last_call = time.monotonic()
        try:
            response = self.client.get(
                BASE_URL + path,
                params=params,
                headers={"Accept": f"application/json;version={API_VERSION}"},
            )
        except httpx.HTTPError as exc:
            raise MarketSourceError(f"GeckoTerminal transport: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise MarketSourceError(f"GeckoTerminal HTTP {response.status_code}")
        return json.loads(response.text, parse_float=Decimal)

    @staticmethod
    def _address(value: str) -> str:
        if not ADDRESS.fullmatch(value):
            raise ValueError("invalid Solana address")
        return value

    def token_pools(self, mint: str) -> dict:
        return self._get(f"/networks/solana/tokens/{self._address(mint)}/pools")

    def trades(self, pool: str) -> dict:
        return self._get(f"/networks/solana/pools/{self._address(pool)}/trades")

    def ohlcv(self, pool: str, token: str, limit: int = 30) -> dict:
        if not 1 <= limit <= 100:
            raise ValueError("pilot candle limit exceeded")
        return self._get(
            f"/networks/solana/pools/{self._address(pool)}/ohlcv/minute",
            {"aggregate": 1, "limit": limit, "currency": "usd", "token": self._address(token)},
        )

    def pool(self, address: str) -> dict:
        return self._get(f"/networks/solana/pools/{self._address(address)}")
