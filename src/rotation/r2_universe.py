"""Rebuild the preregistered R2 research universe from archived public responses."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .market import parse_candles, parse_pool

# Search term, exact mint and primary pool; each mint is independently checked
# against finalized getAccountInfo in the matching indexed archive.
SEEDS = (
    (
        "BONK",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "5zpyutJu9ee6jFymDGoK7F6S5Kczqtc9FomP3ueKuyA9",
    ),
    (
        "WIF",
        "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
    ),
    (
        "PENGU",
        "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv",
        "DdMA1cHcHEqYfttc1z1sJEY978CcU1pyjNuTWTNmdvzU",
    ),
    (
        "POPCAT",
        "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo",
    ),
    (
        "FARTCOIN",
        "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
        "Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw",
    ),
    (
        "MEW",
        "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
        "879F697iuDJGMevRkRcnW21fcXiAeLJK1ffsw2ATebce",
    ),
    (
        "BOME",
        "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",
        "DSUvc5qf5LJHHV5e2tD184ixotSnCnwj7i4jJa4Xsrmt",
    ),
    (
        "PNUT",
        "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump",
        "4AZRPNEfCJ7iw28rJu5aUyeQhYcvdcNm8cswyL51AY9i",
    ),
    (
        "GOAT",
        "CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump",
        "9Tb2ohu5P16BpBarqd3N27WnkF51Ukfs8Z1GzzLDxVZW",
    ),
    (
        "PUMP",
        "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn",
        "2uF4Xh61rDwxnG9woyxsVQP7zuA6kLFpb3NvnRQeoiSd",
    ),
    (
        "GIGA",
        "63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9",
        "4xxM4cdb6MEsCxM52xvYqkNbzvdeWWsPDZrBcTqVGUar",
    ),
    (
        "MOODENG",
        "ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY",
        "22WrmyTj8x2TRVQen3fxxi2r4Rn6JDHWoMTpsSmn8RUd",
    ),
)


def _archive(root: Path, number: int) -> tuple[dict, dict]:
    receipt = json.loads((root / "source" / f"attempt-{number:04}.json").read_text())
    if receipt["http_status"] != 200:
        raise ValueError(f"source attempt {number} did not succeed")
    return receipt, json.loads(receipt["body"], parse_float=Decimal)


def build_universe(root: str | Path) -> dict:
    root = Path(root)
    records = []
    for index, (symbol, mint, pool_address) in enumerate(SEEDS):
        search_no = index + 3
        candle_no = None if symbol == "PUMP" else index + (15 if index < 9 else 14)
        mint_no = None if symbol == "PUMP" else index + (26 if index < 9 else 25)
        search_receipt, search = _archive(root, search_no)
        candle_receipt, daily = _archive(root, candle_no) if candle_no else (None, None)
        mint_receipt, account = _archive(root, mint_no) if mint_no else (None, None)
        matching = [
            item for item in search["data"] if item["attributes"]["address"] == pool_address
        ]
        if len(matching) != 1:
            raise ValueError(f"missing unique exact pool for {symbol}")
        entry = matching[0]
        parsed = parse_pool(entry, datetime.fromisoformat(search_receipt["received_at"]))
        if mint not in {parsed.base_mint, parsed.quote_mint}:
            raise ValueError(f"mint mismatch for {symbol}")
        info = account["result"]["value"] if account else None
        if info and (
            info["owner"] != "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            or info["data"]["parsed"]["type"] != "mint"
        ):
            raise ValueError(f"not an SPL mint: {symbol}")
        candles = (
            parse_candles(
                daily,
                pool_address,
                mint,
                datetime.fromisoformat(candle_receipt["received_at"]),
                seconds=86400,
            )
            if daily
            else []
        )
        attrs = entry["attributes"]
        h24 = attrs.get("transactions", {}).get("h24", {})
        count = int(h24.get("buys", 0)) + int(h24.get("sells", 0))
        reasons = []
        if parsed.reserve_usd is None or parsed.reserve_usd < Decimal("100000"):
            reasons.append("pool_reserve_below_research_threshold")
        if parsed.volume_h24_usd is None or parsed.volume_h24_usd < Decimal("25000"):
            reasons.append("rolling_h24_volume_below_research_threshold")
        if count < 100:
            reasons.append("rolling_h24_trade_count_below_research_threshold")
        if symbol != "PUMP" and len(candles) < 10:
            reasons.append("fewer_than_10_closed_daily_candles")
        if symbol == "PUMP":
            reasons.append("platform_token_outside_speculative_coin_scope")
        records.append(
            {
                "network": "solana",
                "symbol": symbol,
                "mint": mint,
                "name": attrs["name"].split(" / ")[0],
                "decimals": info["data"]["parsed"]["info"]["decimals"] if info else None,
                "status": "research_candidate" if not reasons else "research_excluded",
                "reasons": reasons,
                "known_at": search_receipt["received_at"],
                "primary_pool": pool_address,
                "pool_name": attrs["name"],
                "pool_created_at": attrs.get("pool_created_at"),
                "token_age_verified": False,
                "dex": entry["relationships"]["dex"]["data"]["id"],
                "quote_mint": parsed.quote_mint if parsed.base_mint == mint else parsed.base_mint,
                "reserve_usd_snapshot": str(parsed.reserve_usd)
                if parsed.reserve_usd is not None
                else None,
                "rolling_h24_volume_usd": str(parsed.volume_h24_usd)
                if parsed.volume_h24_usd is not None
                else None,
                "rolling_h24_trades": count,
                "closed_daily_candles": len(candles),
                "market_received_at": search_receipt["received_at"],
                "source_attempts": [n for n in (search_no, candle_no, mint_no) if n],
                "source_hashes": [search_receipt["response_hash"]]
                + ([candle_receipt["response_hash"]] if candle_receipt else [])
                + ([mint_receipt["response_hash"]] if mint_receipt else []),
            }
        )
    return {
        "scope": "research_proposal_not_user_watchlist",
        "criteria_version": "r2-preregistered-1",
        "records": records,
    }
