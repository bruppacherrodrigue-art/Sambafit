"""Interruptible bounded ingestion. Every page checkpoint follows durable writes."""

import os
from datetime import datetime, timezone

from .solana import PARSER_VERSION, RpcError, SolanaDecoder

TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)


def stopped() -> bool:
    return os.getenv("ROTATION_KILL_SWITCH") == "1"


def discover_token_accounts(rpc, wallet: str, max_accounts: int = 20) -> list[str]:
    """Current accounts only. Closed historical accounts remain an explicit gap."""
    addresses: list[str] = []
    for program in TOKEN_PROGRAMS:
        response = rpc.token_accounts(wallet, program)
        for item in (response or {}).get("value", []):
            if len(addresses) >= max_accounts:
                return addresses
            addresses.append(item["pubkey"])
    return addresses


def backfill_wallet(
    store,
    rpc,
    wallet: str,
    *,
    address: str | None = None,
    page_size: int = 20,
    max_pages: int = 2,
    max_calls: int = 100,
    observed_at: datetime | None = None,
    swap_program_ids: set[str] | None = None,
    earliest_at: datetime | None = None,
) -> dict:
    if page_size < 1 or page_size > 100 or max_pages < 1 or max_pages > 100:
        raise ValueError("backfill limits exceeded")
    observed_at = observed_at or datetime.now(timezone.utc)
    address = address or wallet
    key = f"{wallet}|{address}"
    checkpoint = store.get_checkpoint(key)
    cursor = checkpoint["cursor"] if checkpoint else None
    pages = checkpoint["pages"] if checkpoint else 0
    new_raw = 0
    calls = 0
    decoder = SolanaDecoder(swap_program_ids or set())
    if address == wallet and checkpoint is None:
        store.add_coverage_gap(
            wallet,
            "historical closed token accounts not discovered; current token accounts need separate scan",
        )
    for _ in range(max_pages):
        if stopped() or calls >= max_calls:
            break
        page = rpc.signatures(address, limit=page_size, before=cursor)
        calls += 1
        if not page:
            store.checkpoint(key, cursor, pages, "partial_closed_accounts")
            break
        for item in page:
            if stopped() or calls >= max_calls:
                break
            if (
                earliest_at
                and item.get("blockTime")
                and datetime.fromtimestamp(item["blockTime"], timezone.utc) < earliest_at
            ):
                break
            try:
                tx = rpc.transaction(item["signature"])
            except RpcError as exc:
                store.add_coverage_gap(wallet, f"getTransaction failed: {exc}")
                break
            calls += 1
            if tx is None:
                store.add_coverage_gap(wallet, f"transaction unavailable: {item['signature']}")
                break
            if store.add_raw(
                item["signature"],
                wallet,
                tx,
                "solana_rpc",
                PARSER_VERSION,
                first_seen_at=observed_at,
            ):
                new_raw += 1
            decoded = decoder.decode(tx, wallet, observed_at)
            store.add_operation(
                item["signature"],
                wallet,
                decoded.operation,
                decoded.fee_lamports,
                decoded.parser_version,
            )
        else:
            cursor = page[-1]["signature"]
            pages += 1
            store.checkpoint(key, cursor, pages, "partial_closed_accounts")
            if len(page) < page_size:
                break
            continue
        break  # Stop on budget, kill switch, age limit or error; replay page safely.
    return {
        "wallet": wallet,
        "address": address,
        "calls": calls,
        "pages": pages,
        "new_raw": new_raw,
        "cursor": cursor,
        "coverage": "partial_closed_accounts",
    }


def collect_wallet_once(
    store,
    rpc,
    wallet: str,
    *,
    page_size: int = 20,
    observed_at: datetime | None = None,
    swap_program_ids: set[str] | None = None,
) -> dict:
    """Polling head; catches up to previous head, with gap if page reaches its cap."""
    observed_at = observed_at or datetime.now(timezone.utc)
    key = f"live:{wallet}"
    previous = store.get_checkpoint(key)
    head = previous["cursor"] if previous else None
    page = rpc.signatures(wallet, limit=page_size)
    decoder = SolanaDecoder(swap_program_ids or set())
    fetched = 0
    for item in reversed(page or []):
        if item["signature"] == head or stopped():
            continue
        tx = rpc.transaction(item["signature"])
        if tx is None:
            store.add_coverage_gap(wallet, f"live transaction unavailable: {item['signature']}")
            return {
                "wallet": wallet,
                "new_raw": fetched,
                "head": head,
                "coverage": "retry_required",
            }
        inserted = store.add_raw(
            item["signature"], wallet, tx, "solana_rpc", PARSER_VERSION, first_seen_at=observed_at
        )
        decoded = decoder.decode(tx, wallet, observed_at)
        store.add_operation(
            item["signature"],
            wallet,
            decoded.operation,
            decoded.fee_lamports,
            decoded.parser_version,
        )
        fetched += int(inserted)
    if page:
        if head and all(item["signature"] != head for item in page) and len(page) >= page_size:
            store.add_coverage_gap(wallet, "live polling page exceeded; backfill required")
        store.checkpoint(key, page[0]["signature"], 1, "partial_closed_accounts")
    return {"wallet": wallet, "new_raw": fetched, "head": page[0]["signature"] if page else head}
