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


@dataclass(frozen=True)
class AggregateFlow:
    source: str
    destination: str
    evidence: str
    amount_usd: Decimal
    seller_entities: int
    buyer_entities: int
    concentration: Decimal
    independence_uncertain: bool
    available_at: datetime


def aggregate_convergence(
    operations: list[Operation],
    at: datetime,
    window: timedelta = timedelta(hours=6),
    entity_groups: dict[str, str] | None = None,
    max_entity_usd: Decimal = Decimal("10000"),
) -> list[AggregateFlow]:
    """Compare bounded reductions and additions; never imply same funds moved A→B."""
    entity_groups = entity_groups or {}
    sold: dict[str, dict[str, Decimal]] = {}
    bought: dict[str, dict[str, Decimal]] = {}
    for operation in operations:
        if (
            not operation.finalized
            or operation.quality != "complete"
            or operation.kind not in {"swap", "sale", "buy"}
            or operation.available_at > at
            or operation.available_at < at - window
        ):
            continue
        group = entity_groups.get(operation.wallet, operation.wallet)
        for leg in operation.legs:
            if leg.value_usd is None or leg.value_usd <= 0:
                continue
            target = sold if leg.delta_base < 0 else bought
            group_values = target.setdefault(leg.mint, {})
            group_values[group] = group_values.get(group, Decimal(0)) + leg.value_usd
    flows = []
    for source, sellers in sold.items():
        seller_values = [min(value, max_entity_usd) for value in sellers.values()]
        seller_total = sum(seller_values, Decimal(0))
        for destination, buyers in bought.items():
            if source == destination:
                continue
            if len(set(sellers) | set(buyers)) < 2:
                continue
            buyer_values = [min(value, max_entity_usd) for value in buyers.values()]
            buyer_total = sum(buyer_values, Decimal(0))
            amount = min(seller_total, buyer_total)
            if amount <= 0:
                continue
            concentration = max([*seller_values, *buyer_values]) / max(seller_total, buyer_total)
            flows.append(
                AggregateFlow(
                    source,
                    destination,
                    "aggregate",
                    amount,
                    len(sellers),
                    len(buyers),
                    concentration,
                    not bool(entity_groups),
                    at,
                )
            )
    return flows


def attribute_rotations(
    operations: list[Operation],
    window: timedelta = timedelta(hours=6),
    stable_mints: set[str] | None = None,
    bridge_mints: set[str] | None = None,
    reserve_mints: set[str] | None = None,
) -> list[Rotation]:
    """Pair bounded sells/buys FIFO. Swaps never seed inference."""
    stable_mints = stable_mints or set()
    bridge_mints = bridge_mints or set()
    reserve_mints = reserve_mints or set()

    def direction(source: str, destination: str) -> str:
        if destination in stable_mints:
            return "to_stable"
        if source in stable_mints:
            return "from_stable"
        if destination in reserve_mints:
            return "to_reserve"
        if source in reserve_mints:
            return "from_reserve"
        return "between_coins"

    rotations: list[Rotation] = []
    sales: dict[str, list[dict]] = {}
    for op in sorted(operations, key=lambda x: (x.economic_at, x.available_at, x.id)):
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
            rotations.append(
                Rotation(
                    source.mint,
                    dest.mint,
                    "direct",
                    direction(source.mint, dest.mint),
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
                        direction(sale["leg"].mint, buy.mint),
                        amount,
                        op.wallet,
                        prev.id,
                        op.id,
                        op.economic_at,
                        max(prev.available_at, op.available_at),
                    )
                )
                sale["remaining"] -= amount
                remaining -= amount
    return rotations
