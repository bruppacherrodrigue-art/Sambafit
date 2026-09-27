"""Shared FIFO consumption of observed reserve credits.

The caller decides whether a consumption is a research rotation. A buyback and
an out-of-universe purchase still spend a credit. Units never cross: base units
of different reserve mints, or an old USD proxy, cannot be mixed.
"""

from datetime import datetime, timedelta
from decimal import Decimal


def consume(pending: list[dict], debit: dict, window: timedelta) -> list[tuple[dict, Decimal]]:
    remaining = Decimal(debit["amount"])
    matches: list[tuple[dict, Decimal]] = []
    for credit in pending:
        if remaining <= 0:
            break
        if (
            credit["wallet"] != debit["wallet"]
            or credit["reserve_mint"] != debit["reserve_mint"]
            or credit["unit"] != debit["unit"]
            or credit["reserve_decimals"] != debit["reserve_decimals"]
            or credit["remaining"] <= 0
        ):
            continue
        gap = datetime.fromisoformat(debit["economic_at"]) - datetime.fromisoformat(
            credit["economic_at"]
        )
        if not timedelta(0) <= gap <= window:
            continue
        amount = min(remaining, credit["remaining"])
        credit["remaining"] -= amount
        remaining -= amount
        matches.append((credit, amount))
    return matches
