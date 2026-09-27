"""Conservative economic operation attribution, with integer token quantities."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .flow_clock import assess_flow_clock
from .reserve_fifo import consume


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
    supersedes_id: str | None = None


@dataclass(frozen=True)
class Rotation:
    source: str
    destination: str | None
    evidence: str
    direction: str
    amount_usd: Decimal | None
    wallet: str
    source_op: str
    destination_op: str | None
    economic_at: datetime
    available_at: datetime
    reserve_mint: str | None = None
    reserve_quantity_base: int | None = None
    sale_value_usd: Decimal | None = None
    buy_value_usd: Decimal | None = None
    valuation_method: str | None = None


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
    max_observation_delay: timedelta = timedelta(minutes=15),
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
            or assess_flow_clock(
                operation.economic_at,
                operation.available_at,
                at,
                max_economic_age=window,
                max_observation_delay=max_observation_delay,
            ).reasons
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
    sales: list[dict] = []
    for op in sorted(operations, key=lambda x: (x.economic_at, x.available_at, x.id)):
        if not op.finalized or op.quality != "complete":
            continue
        negative = [x for x in op.legs if x.delta_base < 0 and x.mint not in bridge_mints]
        positive = [x for x in op.legs if x.delta_base > 0 and x.mint not in bridge_mints]
        if op.kind == "swap":
            if len(negative) != 1 or len(positive) != 1:
                continue
            source, dest = negative[0], positive[0]
            if source.mint == dest.mint:
                continue
            rotations.append(
                Rotation(
                    source.mint,
                    dest.mint,
                    "direct",
                    direction(source.mint, dest.mint),
                    min(source.value_usd, dest.value_usd)
                    if source.value_usd is not None and dest.value_usd is not None
                    else None,
                    op.wallet,
                    op.id,
                    op.id,
                    op.economic_at,
                    op.available_at,
                    source.mint
                    if source.mint in reserve_mints
                    else dest.mint
                    if dest.mint in reserve_mints
                    else None,
                    abs(source.delta_base)
                    if source.mint in reserve_mints
                    else dest.delta_base
                    if dest.mint in reserve_mints
                    else None,
                    source.value_usd,
                    dest.value_usd,
                    "two_legs_point_in_time"
                    if source.value_usd is not None and dest.value_usd is not None
                    else None,
                )
            )
        is_sale = op.kind == "sale" or (
            op.kind == "swap"
            and len(negative) == len(positive) == 1
            and positive[0].mint in reserve_mints
            and negative[0].mint not in reserve_mints
        )
        is_buy = op.kind == "buy" or (
            op.kind == "swap"
            and len(negative) == len(positive) == 1
            and negative[0].mint in reserve_mints
            and positive[0].mint not in reserve_mints
        )
        if is_sale and len(negative) == 1:
            reserve = next((leg for leg in positive if leg.mint in reserve_mints), None)
            unit = "reserve_base" if reserve else "usd_proxy"
            amount = Decimal(reserve.delta_base) if reserve else negative[0].value_usd
            if amount is None or amount <= 0:
                continue
            sales.append(
                {
                    "op": op,
                    "leg": negative[0],
                    "wallet": op.wallet,
                    "reserve_mint": reserve.mint if reserve else "__legacy_usd_proxy__",
                    "unit": unit,
                    "reserve_decimals": reserve.decimals if reserve else 0,
                    "economic_at": op.economic_at.isoformat(),
                    "amount": amount,
                    "remaining": amount,
                }
            )
        elif is_buy and len(positive) == 1:
            buy = positive[0]
            reserve = next((leg for leg in negative if leg.mint in reserve_mints), None)
            unit = "reserve_base" if reserve else "usd_proxy"
            amount = Decimal(abs(reserve.delta_base)) if reserve else buy.value_usd
            if amount is None or amount <= 0:
                continue
            debit = {
                "wallet": op.wallet,
                "reserve_mint": reserve.mint if reserve else "__legacy_usd_proxy__",
                "unit": unit,
                "reserve_decimals": reserve.decimals if reserve else 0,
                "economic_at": op.economic_at.isoformat(),
                "amount": amount,
            }
            for sale, matched in consume(sales, debit, window):
                prev = sale["op"]
                if sale["leg"].mint == buy.mint:
                    continue  # Same-coin repurchase spends credit but is no rotation.
                sale_value = (
                    sale["leg"].value_usd * matched / sale["amount"]
                    if sale["leg"].value_usd is not None
                    else None
                )
                buy_value = buy.value_usd * matched / amount if buy.value_usd is not None else None
                rotations.append(
                    Rotation(
                        sale["leg"].mint,
                        buy.mint,
                        "inferred",
                        direction(sale["leg"].mint, buy.mint),
                        min(sale_value, buy_value)
                        if sale_value is not None and buy_value is not None
                        else None,
                        op.wallet,
                        prev.id,
                        op.id,
                        op.economic_at,
                        max(prev.available_at, op.available_at),
                        reserve.mint if reserve else None,
                        int(matched) if reserve else None,
                        sale_value,
                        buy_value,
                        "reserve_base_conserved" if reserve else "legacy_usd_proxy",
                    )
                )
    return rotations
