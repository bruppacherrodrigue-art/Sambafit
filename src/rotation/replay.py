"""Availability-clock replay using the same attribution and decision functions as live."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import groupby

from .engine import AggregateFlow, Operation, Rotation, aggregate_convergence, attribute_rotations
from .signals import Decision, MarketBar, decide, market_features


@dataclass(frozen=True)
class DecisionRecord:
    at: datetime
    pair: str
    decision: Decision


@dataclass(frozen=True)
class ReplayResult:
    rotations: tuple[Rotation, ...]
    decisions: tuple[DecisionRecord, ...]
    aggregate_flows: tuple[AggregateFlow, ...] = ()


def replay(
    operations: list[Operation],
    bars: list[MarketBar],
    until: datetime,
    *,
    stable_mints: set[str] | None = None,
    bridge_mints: set[str] | None = None,
    reserve_mints: set[str] | None = None,
    mint_known_at: dict[str, datetime] | None = None,
    wallet_known_at: dict[str, datetime] | None = None,
    eligible_mints: set[str] | None = None,
    eligible_wallets: set[str] | None = None,
    invalidation_loss: Decimal = Decimal("0.10"),
) -> ReplayResult:
    """Never evaluate a bar or operation before its local availability timestamp."""
    events: list[tuple[datetime, int, object]] = []
    events.extend((o.available_at, 0, o) for o in operations if o.available_at <= until)
    events.extend((b.available_at, 1, b) for b in bars if b.available_at <= until)
    events.sort(key=lambda x: (x[0], x[1]))
    active: dict[tuple[str, str], Operation] = {}
    visible_bars: list[MarketBar] = []
    records: list[DecisionRecord] = []
    current_pair: str | None = None
    entry_price: Decimal | None = None
    last_state: tuple[str, str] | None = None
    rotations: list[Rotation] = []
    aggregate: list[AggregateFlow] = []
    mint_known_at = mint_known_at or {}
    wallet_known_at = wallet_known_at or {}
    for at, batch in groupby(events, key=lambda x: x[0]):
        retracted = False
        for _, _, event in batch:
            if isinstance(event, Operation):
                if eligible_wallets is not None and event.wallet not in eligible_wallets:
                    continue
                if event.available_at < wallet_known_at.get(event.wallet, event.available_at):
                    continue
                if event.kind == "retracted":
                    retracted = active.pop((event.wallet, event.signature), None) is not None
                else:
                    active[(event.wallet, event.signature)] = event
            else:
                visible_bars.append(event)
        rotations = attribute_rotations(
            list(active.values()),
            stable_mints=stable_mints,
            bridge_mints=bridge_mints,
            reserve_mints=reserve_mints,
        )
        rotations = [
            r
            for r in rotations
            if (
                eligible_mints is None
                or (
                    r.source in eligible_mints
                    and (r.destination is None or r.destination in eligible_mints)
                )
            )
            and r.available_at >= mint_known_at.get(r.source, r.available_at)
            and (
                r.destination is None
                or r.available_at >= mint_known_at.get(r.destination, r.available_at)
            )
        ]
        aggregate = [
            flow
            for flow in aggregate_convergence(list(active.values()), at)
            if (
                eligible_mints is None
                or (flow.source in eligible_mints and flow.destination in eligible_mints)
            )
            and flow.available_at >= mint_known_at.get(flow.source, flow.available_at)
            and flow.available_at >= mint_known_at.get(flow.destination, flow.available_at)
        ]
        relevant = [r for r in rotations if r.direction == "between_coins"]
        if relevant:
            latest = max(
                relevant,
                key=lambda r: (r.available_at, r.economic_at, r.source_op, r.destination_op or ""),
            )
            pair = f"{latest.source}:{latest.destination}"
            if pair != current_pair:
                current_pair, entry_price = pair, None
            decision = decide(relevant, visible_bars, at)
            feature = market_features(visible_bars, latest.destination, at)
            if decision.state in ("candidate", "confirmed") and entry_price is None:
                entry_price = feature.last_price
            if (
                entry_price
                and feature.last_price
                and feature.last_price < entry_price * (Decimal(1) - invalidation_loss)
            ):
                decision = Decision(
                    "invalidated",
                    decision.quality,
                    decision.score,
                    decision.components,
                    decision.reasons + ("loss threshold observed",),
                )
        elif retracted and current_pair:
            pair = current_pair
            decision = Decision("observing", "retracted", 0, (), ("source transaction retracted",))
            entry_price = None
        else:
            continue
        status = (pair, decision.state)
        if status != last_state or retracted:
            records.append(DecisionRecord(at, pair, decision))
            last_state = status
    return ReplayResult(tuple(rotations), tuple(records), tuple(aggregate))
