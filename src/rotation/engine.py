"""Conservative economic operation attribution, with integer token quantities."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Leg:
    mint: str
    delta_base: int
    decimals: int
    usd_price: Decimal | None

    @property
    def value_usd(self) -> Decimal | None:
        if self.usd_price is None:
            return None
        return Decimal(abs(self.delta_base)) * self.usd_price / (Decimal(10) ** self.decimals)


@dataclass(frozen=True)
class Operation:
    id: str
    wallet: str
    signature: str
    economic_at: datetime
    available_at: datetime
    kind: str
    legs: tuple[Leg, ...]
    finalized: bool
    quality: str


@dataclass(frozen=True)
class Rotation:
    source: str
    destination: str | None
    evidence: str
    direction: str
    amount_usd: Decimal
    wallet: str
    source_op: str
    destination_op: str | None
    economic_at: datetime
    available_at: datetime


def attribute_rotations(
    operations: list[Operation],
    window: timedelta = timedelta(hours=6),
    stable_mints: set[str] | None = None,
    bridge_mints: set[str] | None = None,
) -> list[Rotation]:
    """Pair bounded sells/buys FIFO. Swaps never seed inference."""
    stable_mints = stable_mints or set()
    bridge_mints = bridge_mints or set()
    rotations: list[Rotation] = []
    sales: dict[str, list[dict]] = {}
    for op in sorted(operations, key=lambda x: (x.available_at, x.economic_at, x.id)):
        if not op.finalized or op.quality != "complete":
            continue
        negative = [x for x in op.legs if x.delta_base < 0 and x.mint not in bridge_mints]
        positive = [x for x in op.legs if x.delta_base > 0 and x.mint not in bridge_mints]
        if op.kind == "swap":
            if len(negative) != 1 or len(positive) != 1:
                continue
            source, dest = negative[0], positive[0]
            if source.mint == dest.mint or source.value_usd is None or dest.value_usd is None:
                continue
            direction = (
                "to_stable"
                if dest.mint in stable_mints
                else "from_stable"
                if source.mint in stable_mints
                else "between_coins"
            )
            rotations.append(
                Rotation(
                    source.mint,
                    dest.mint,
                    "direct",
                    direction,
                    min(source.value_usd, dest.value_usd),
                    op.wallet,
                    op.id,
                    op.id,
                    op.economic_at,
                    op.available_at,
                )
            )
        elif op.kind == "sale" and len(negative) == 1 and negative[0].value_usd is not None:
            sales.setdefault(op.wallet, []).append(
                {"op": op, "leg": negative[0], "remaining": negative[0].value_usd}
            )
        elif op.kind == "buy" and len(positive) == 1 and positive[0].value_usd is not None:
            buy = positive[0]
            remaining = buy.value_usd
            for sale in sales.get(op.wallet, []):
                if remaining <= 0:
                    break
                prev = sale["op"]
                if (
                    sale["remaining"] <= 0
                    or prev.economic_at > op.economic_at
                    or op.economic_at - prev.economic_at > window
                    or sale["leg"].mint == buy.mint
                ):
                    continue
                amount = min(remaining, sale["remaining"])
                rotations.append(
                    Rotation(
                        sale["leg"].mint,
                        buy.mint,
                        "inferred",
                        "between_coins",
                        amount,
                        op.wallet,
                        prev.id,
                        op.id,
                        op.economic_at,
                        op.available_at,
                    )
                )
                sale["remaining"] -= amount
                remaining -= amount
    return rotations
