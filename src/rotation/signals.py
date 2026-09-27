"""Availability-clock, versioned research decisions for exact memecoin pairs."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .engine import Operation, Rotation
from .flow_clock import assess_flow_clock

SCORE_VERSION = "r3.1-pair-hypothesis-2"


@dataclass(frozen=True)
class MarketBar:
    mint: str
    close_at: datetime
    available_at: datetime
    close_usd: Decimal
    volume_usd: Decimal | None
    liquidity_usd: Decimal | None
    interval_seconds: int = 60
    volume_kind: str = "interval"


@dataclass(frozen=True)
class Features:
    last_price: Decimal | None
    range_position: Decimal | None
    return_fraction: Decimal | None
    volume_acceleration: Decimal | None
    liquidity_usd: Decimal | None
    last_available_at: datetime | None
    last_close_at: datetime | None
    last_return_fraction: Decimal | None = None
    volatility: Decimal | None = None
    volume_usd: Decimal | None = None
    coverage_reason: str | None = None


@dataclass(frozen=True)
class Decision:
    state: str
    quality: str
    score: int
    components: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]
    version: str = SCORE_VERSION
    execution_quality: str = "not_evaluated"
    metrics: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class PairPolicy:
    lookback_bars: int = 24
    min_bars: int = 3
    max_age: timedelta = timedelta(minutes=30)
    max_pair_skew: timedelta = timedelta(seconds=0)
    flow_window: timedelta = timedelta(hours=6)
    max_economic_flow_age: timedelta = timedelta(hours=6)
    max_observation_delay: timedelta = timedelta(minutes=15)
    min_flow_usd: Decimal = Decimal("1000")
    max_entity_usd: Decimal = Decimal("10000")
    min_source_range: Decimal = Decimal("0.65")
    max_destination_range: Decimal = Decimal("0.45")
    min_relative_step: Decimal = Decimal("0")
    min_liquidity_usd: Decimal = Decimal("10000")
    confirmed_entities: int = 2
    confirmed_score: int = 55


def _visible_bars(bars: list[MarketBar], mint: str, at: datetime, lookback: int) -> list[MarketBar]:
    latest: dict[datetime, MarketBar] = {}
    for bar in bars:
        if bar.mint != mint or bar.close_at > at or bar.available_at > at or bar.close_usd <= 0:
            continue
        previous = latest.get(bar.close_at)
        if previous is None or bar.available_at > previous.available_at:
            latest[bar.close_at] = bar
    return sorted(latest.values(), key=lambda bar: bar.close_at)[-lookback:]


def market_features(bars: list[MarketBar], mint: str, at: datetime, lookback: int = 24) -> Features:
    past = _visible_bars(bars, mint, at, lookback)
    if not past:
        return Features(
            None, None, None, None, None, None, None, coverage_reason="missing_closed_bar"
        )
    prices = [bar.close_usd for bar in past]
    low, high = min(prices), max(prices)
    position = (prices[-1] - low) / (high - low) if high > low else None
    change = prices[-1] / prices[0] - 1 if len(prices) > 1 else None
    interval = past[-1].interval_seconds
    regular = all(
        bar.interval_seconds == interval
        and bar.close_at - previous.close_at == timedelta(seconds=interval)
        for previous, bar in zip(past, past[1:])
    )
    interval_volume = all(
        bar.volume_kind == "interval" and bar.volume_usd is not None for bar in past
    )
    accel = (
        past[-1].volume_usd / past[-2].volume_usd
        if len(past) > 1 and regular and interval_volume and past[-2].volume_usd > 0
        else None
    )
    returns = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    volatility = (
        sum((abs(value) for value in returns), Decimal(0)) / len(returns)
        if returns and regular
        else None
    )
    return Features(
        prices[-1],
        position,
        change,
        accel,
        past[-1].liquidity_usd,
        past[-1].available_at,
        past[-1].close_at,
        returns[-1] if returns and regular else None,
        volatility,
        past[-1].volume_usd if interval_volume else None,
        None if regular and interval_volume else "gap_or_overlapping_volume",
    )


def decide_pairs(
    rotations: list[Rotation],
    bars: list[MarketBar],
    at: datetime,
    *,
    eligible_mints: set[str] | None = None,
    policy: PairPolicy = PairPolicy(),
    entity_groups: dict[str, str] | None = None,
    operations: list[Operation] | None = None,
) -> dict[tuple[str, str], Decision]:
    visible = [
        r
        for r in rotations
        if r.available_at <= at
        and r.destination is not None
        and r.source != r.destination
        and r.direction == "between_coins"
        and (
            eligible_mints is None
            or (r.source in eligible_mints and r.destination in eligible_mints)
        )
    ]
    return {
        pair: decide(
            visible,
            bars,
            at,
            pair=pair,
            policy=policy,
            entity_groups=entity_groups,
            operations=operations,
        )
        for pair in sorted({(r.source, r.destination) for r in visible})
    }


def decide(
    rotations: list[Rotation],
    bars: list[MarketBar],
    at: datetime,
    max_age: timedelta | None = None,
    min_liquidity_usd: Decimal | None = None,
    entity_groups: dict[str, str] | None = None,
    max_entity_usd: Decimal | None = None,
    *,
    pair: tuple[str, str] | None = None,
    policy: PairPolicy = PairPolicy(),
    operations: list[Operation] | None = None,
) -> Decision:
    """Evaluate one pair; an ambiguous call never selects a destination silently."""
    if max_age is not None or min_liquidity_usd is not None or max_entity_usd is not None:
        policy = PairPolicy(
            **{
                **policy.__dict__,
                **({"max_age": max_age} if max_age is not None else {}),
                **(
                    {"min_liquidity_usd": min_liquidity_usd}
                    if min_liquidity_usd is not None
                    else {}
                ),
                **({"max_entity_usd": max_entity_usd} if max_entity_usd is not None else {}),
            }
        )
    visible = [
        r
        for r in rotations
        if (r.available_at <= at or pair is not None)
        and r.destination is not None
        and r.source != r.destination
        and r.direction == "between_coins"
    ]
    pairs = {(r.source, r.destination) for r in visible}
    if pair is None:
        if not pairs:
            return Decision("observing", "insufficient", 0, (), ("no_visible_rotation",))
        if len(pairs) != 1:
            return Decision("observing", "ambiguous_pair", 0, (), ("explicit_pair_required",))
        pair = next(iter(pairs))
    matching = [r for r in visible if (r.source, r.destination) == pair]
    clocks = [
        assess_flow_clock(
            r.economic_at,
            r.available_at,
            at,
            max_economic_age=policy.max_economic_flow_age,
            max_observation_delay=policy.max_observation_delay,
        )
        for r in matching
    ]
    recent = [
        r
        for r, clock in zip(matching, clocks)
        if not clock.reasons and clock.economic_age <= policy.flow_window
    ]
    if not recent:
        reasons = tuple(sorted({reason for clock in clocks for reason in clock.reasons}))
        latest = (
            max(clocks, key=lambda clock: -clock.economic_age.total_seconds()) if clocks else None
        )
        return Decision(
            "expired" if not reasons or "economic_flow_stale" in reasons else "observing",
            "invalid_clock"
            if "incoherent_or_future_economic_clock" in reasons
            else "stale_flow"
            if reasons
            else "complete",
            0,
            (),
            reasons or ("flow_window_expired",),
            metrics=(
                (
                    "attributed_amount_usd",
                    str(sum((r.amount_usd or Decimal(0) for r in matching), Decimal(0))),
                ),
                (
                    "evidence_operations",
                    ",".join(sorted({f"{r.source_op}>{r.destination_op}" for r in matching})),
                ),
                (
                    "economic_age_seconds",
                    str(latest.economic_age.total_seconds()) if latest else None,
                ),
                (
                    "observation_delay_seconds",
                    str(latest.observation_delay.total_seconds()) if latest else None,
                ),
            ),
        )
    source_bars = _visible_bars(bars, pair[0], at, policy.lookback_bars)
    destination_bars = _visible_bars(bars, pair[1], at, policy.lookback_bars)
    if not source_bars or not destination_bars:
        return Decision("observing", "missing_market", 0, (), ("missing_A_or_B_closed_bar",))
    if (
        at - source_bars[-1].close_at > policy.max_age
        or at - destination_bars[-1].close_at > policy.max_age
    ):
        return Decision("observing", "stale", 0, (), ("A_or_B_market_stale",))
    source = market_features(bars, pair[0], at, policy.lookback_bars)
    destination = market_features(bars, pair[1], at, policy.lookback_bars)
    if (
        len(source_bars) < policy.min_bars
        or len(destination_bars) < policy.min_bars
        or source.coverage_reason
        or destination.coverage_reason
        or source.range_position is None
        or destination.range_position is None
        or source.volume_acceleration is None
        or destination.volume_acceleration is None
    ):
        return Decision("observing", "incomplete_market", 0, (), ("A_or_B_history_incomplete",))
    if (
        abs(source_bars[-1].close_at - destination_bars[-1].close_at) > policy.max_pair_skew
        or abs(source_bars[-2].close_at - destination_bars[-2].close_at) > policy.max_pair_skew
        or source_bars[-1].interval_seconds != destination_bars[-1].interval_seconds
    ):
        return Decision("observing", "misaligned_market", 0, (), ("A_B_close_times_misaligned",))
    relative_step = (destination_bars[-1].close_usd / source_bars[-1].close_usd) / (
        destination_bars[-2].close_usd / source_bars[-2].close_usd
    ) - 1
    groups: dict[str, Decimal] = {}
    missing_value = False
    for rotation in recent:
        if rotation.amount_usd is None:
            missing_value = True
            continue
        group = (entity_groups or {}).get(rotation.wallet, rotation.wallet)
        groups[group] = groups.get(group, Decimal(0)) + rotation.amount_usd
    amount = sum((min(value, policy.max_entity_usd) for value in groups.values()), Decimal(0))
    net = {pair[0]: Decimal(0), pair[1]: Decimal(0)}
    net_coverage = {pair[0]: True, pair[1]: True}
    for operation in operations or []:
        if (
            not operation.finalized
            or operation.quality != "complete"
            or not at - policy.flow_window <= operation.economic_at <= at
            or not operation.available_at <= at
            or operation.available_at - operation.economic_at > policy.max_observation_delay
        ):
            continue
        for leg in operation.legs:
            if leg.mint not in net:
                continue
            if leg.value_usd is None:
                net_coverage[leg.mint] = False
            else:
                net[leg.mint] += leg.value_usd * (1 if leg.delta_base > 0 else -1)
    first_economic_at = min(rotation.economic_at for rotation in recent)

    def prior_price(mint: str) -> Decimal | None:
        candidates = [
            bar
            for bar in _visible_bars(bars, mint, at, policy.lookback_bars)
            if bar.close_at <= first_economic_at
        ]
        return candidates[-1].close_usd if candidates else None

    prior_a, prior_b = prior_price(pair[0]), prior_price(pair[1])
    metrics = (
        (
            "attributed_amount_usd",
            str(sum((r.amount_usd or Decimal(0) for r in recent), Decimal(0))),
        ),
        (
            "evidence_operations",
            ",".join(sorted({f"{r.source_op}>{r.destination_op}" for r in recent})),
        ),
        ("evidence_wallets", ",".join(sorted({r.wallet for r in recent}))),
        ("economic_age_seconds", str((at - first_economic_at).total_seconds())),
        (
            "observation_delay_seconds",
            str(max((r.available_at - r.economic_at).total_seconds() for r in recent)),
        ),
        ("source_range", str(source.range_position)),
        ("destination_range", str(destination.range_position)),
        ("source_return", str(source.return_fraction)),
        ("destination_return", str(destination.return_fraction)),
        ("source_volatility", str(source.volatility) if source.volatility is not None else None),
        (
            "destination_volatility",
            str(destination.volatility) if destination.volatility is not None else None,
        ),
        (
            "source_volume_interval_usd",
            str(source.volume_usd) if source.volume_usd is not None else None,
        ),
        (
            "destination_volume_interval_usd",
            str(destination.volume_usd) if destination.volume_usd is not None else None,
        ),
        ("source_volume_acceleration", str(source.volume_acceleration)),
        ("destination_volume_acceleration", str(destination.volume_acceleration)),
        ("relative_step", str(relative_step)),
        (
            "source_net_observed_usd",
            str(net[pair[0]]) if operations is not None and net_coverage[pair[0]] else None,
        ),
        (
            "destination_net_observed_usd",
            str(net[pair[1]]) if operations is not None and net_coverage[pair[1]] else None,
        ),
        ("observed_delay_seconds", str((at - first_economic_at).total_seconds())),
        ("source_prior_move", str(source.last_price / prior_a - 1) if prior_a else None),
        ("destination_prior_move", str(destination.last_price / prior_b - 1) if prior_b else None),
        (
            "source_liquidity_usd",
            str(source.liquidity_usd) if source.liquidity_usd is not None else None,
        ),
        (
            "destination_liquidity_usd",
            str(destination.liquidity_usd) if destination.liquidity_usd is not None else None,
        ),
    )
    execution = (
        "liquidity_snapshot_available"
        if source.liquidity_usd is not None
        and destination.liquidity_usd is not None
        and min(source.liquidity_usd, destination.liquidity_usd) >= policy.min_liquidity_usd
        else "blocked_missing_or_low_liquidity"
    )
    if missing_value:
        return Decision(
            "observing",
            "unvalued_flow",
            0,
            (),
            ("rotation_USD_unknown",),
            execution_quality=execution,
            metrics=metrics,
        )
    reasons = []
    if source.range_position < policy.min_source_range:
        reasons.append("source_not_high_in_range")
    if destination.range_position > policy.max_destination_range:
        reasons.append("destination_not_low_in_range")
    if source.last_return_fraction is None or source.last_return_fraction > 0:
        reasons.append("source_not_reducing")
    if destination.last_return_fraction is None or destination.last_return_fraction <= 0:
        reasons.append("destination_not_recovering")
    if relative_step <= policy.min_relative_step:
        reasons.append("relative_force_not_improving")
    if amount < policy.min_flow_usd:
        reasons.append("flow_below_research_threshold")
    components = (
        ("flow", min(30, int(amount / Decimal("100")))),
        ("entity_diversity", min(20, len(groups) * 10)),
        ("direct_evidence", 15 if any(r.evidence == "direct" for r in recent) else 5),
        ("source_range", 10 if source.range_position >= policy.min_source_range else 0),
        (
            "destination_range",
            10 if destination.range_position <= policy.max_destination_range else 0,
        ),
        ("relative_force", 10 if relative_step > policy.min_relative_step else 0),
        ("persistence", 0),
    )
    score = sum(value for _, value in components)
    state = (
        "observing"
        if reasons
        else "confirmed"
        if len(groups) >= policy.confirmed_entities and score >= policy.confirmed_score
        else "candidate"
    )
    return Decision(
        state,
        "complete",
        score,
        components,
        tuple(reasons)
        + (
            f"pair={pair[0]}:{pair[1]}",
            f"capped_flow_usd={amount}",
            f"relative_step={relative_step}",
            f"source_range={source.range_position}",
            f"destination_range={destination.range_position}",
            f"entities={len(groups)}; links_uncertain",
        ),
        execution_quality=execution,
        metrics=metrics,
    )
