"""Point-in-time market features and versioned hypothesis score."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .engine import Rotation

SCORE_VERSION = "hypothesis-1"


@dataclass(frozen=True)
class MarketBar:
    mint: str
    close_at: datetime
    available_at: datetime
    close_usd: Decimal
    volume_usd: Decimal
    liquidity_usd: Decimal | None


@dataclass(frozen=True)
class Features:
    last_price: Decimal | None
    range_position: Decimal | None
    return_fraction: Decimal | None
    volume_acceleration: Decimal | None
    liquidity_usd: Decimal | None
    last_available_at: datetime | None


@dataclass(frozen=True)
class Decision:
    state: str
    quality: str
    score: int
    components: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]
    version: str = SCORE_VERSION


def market_features(bars: list[MarketBar], mint: str, at: datetime, lookback: int = 24) -> Features:
    past = sorted(
        (
            b
            for b in bars
            if b.mint == mint and b.close_at <= at and b.available_at <= at and b.close_usd > 0
        ),
        key=lambda b: b.close_at,
    )[-lookback:]
    if not past:
        return Features(None, None, None, None, None, None)
    prices = [b.close_usd for b in past]
    low, high = min(prices), max(prices)
    position = (prices[-1] - low) / (high - low) if high > low else None
    change = prices[-1] / prices[0] - 1 if len(prices) > 1 else None
    accel = (
        past[-1].volume_usd / past[-2].volume_usd
        if len(past) > 1 and past[-2].volume_usd > 0
        else None
    )
    return Features(
        prices[-1], position, change, accel, past[-1].liquidity_usd, past[-1].available_at
    )


def decide(
    rotations: list[Rotation],
    bars: list[MarketBar],
    at: datetime,
    max_age: timedelta = timedelta(minutes=30),
    min_liquidity_usd: Decimal = Decimal("10000"),
    entity_groups: dict[str, str] | None = None,
    max_entity_usd: Decimal = Decimal("10000"),
) -> Decision:
    visible = [
        r
        for r in rotations
        if r.available_at <= at and r.destination is not None and r.direction == "between_coins"
    ]
    if not visible:
        return Decision("observing", "insufficient", 0, (), ("no visible rotation",))
    destination = visible[-1].destination
    features = market_features(bars, destination, at)
    if features.last_available_at is None:
        return Decision("observing", "missing_market", 0, (), ("missing closed market bar",))
    if at - features.last_available_at > max_age:
        return Decision("observing", "stale", 0, (), ("market data stale",))
    if features.liquidity_usd is None or features.liquidity_usd < min_liquidity_usd:
        return Decision("observing", "missing_liquidity", 0, (), ("liquidity unavailable or low",))
    recent = [
        r
        for r in visible
        if r.destination == destination and at - r.available_at <= timedelta(hours=6)
    ]
    groups: dict[str, Decimal] = {}
    for rotation in recent:
        group = (entity_groups or {}).get(rotation.wallet, rotation.wallet)
        groups[group] = groups.get(group, Decimal(0)) + rotation.amount_usd
    entities = len(groups)
    amount = sum((min(value, max_entity_usd) for value in groups.values()), Decimal(0))
    components = (
        ("flow", min(30, int(amount / Decimal("1000")))),
        ("diversity", min(25, entities * 8)),
        ("direct_evidence", 15 if any(r.evidence == "direct" for r in recent) else 5),
        (
            "market",
            15 if features.return_fraction is not None and features.return_fraction > 0 else 5,
        ),
        ("persistence", 0),  # Only a later observed revision may add this.
    )
    score = sum(value for _, value in components)
    state = "confirmed" if entities >= 2 and score >= 55 else "candidate"
    return Decision(
        state,
        "complete",
        score,
        components,
        (
            f"{entities} observed entities",
            f"capped attributed USD {amount}",
            "unknown links do not prove independence",
        ),
    )
