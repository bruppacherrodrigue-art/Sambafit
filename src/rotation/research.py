"""Point-in-time valuation and descriptive event study. No performance claims."""

import random
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from .engine import Operation
from .replay import ReplayResult
from .signals import MarketBar


def price_operations(
    operations: list[Operation],
    bars: list[MarketBar],
    max_price_age: timedelta = timedelta(minutes=30),
) -> list[Operation]:
    """Use a close known by decision time that also precedes the economic trade."""
    priced: list[Operation] = []
    for op in operations:
        legs = []
        for leg in op.legs:
            if leg.usd_price is not None:
                legs.append(leg)
                continue
            candidates = [
                bar
                for bar in bars
                if bar.mint == leg.mint
                and bar.close_at <= op.economic_at
                and bar.available_at <= op.available_at
                and op.economic_at - bar.close_at <= max_price_age
            ]
            bar = (
                max(candidates, key=lambda x: (x.close_at, x.available_at)) if candidates else None
            )
            legs.append(replace(leg, usd_price=bar.close_usd if bar else None))
        priced.append(replace(op, legs=tuple(legs)))
    return priced


def study_events(
    result: ReplayResult, bars: list[MarketBar], horizons_minutes: tuple[int, ...] = (60, 240, 1440)
) -> dict:
    """Forward B/A return from decision time; episodes overlapping a horizon collapse."""
    if not horizons_minutes or any(x <= 0 for x in horizons_minutes):
        raise ValueError("horizons must be positive")
    embargo = timedelta(minutes=max(horizons_minutes))
    episodes = []
    for record in result.decisions:
        if record.decision.state not in ("candidate", "confirmed") or ":" not in record.pair:
            continue
        if any(
            previous.pair == record.pair and record.at - previous.at < embargo
            for previous in episodes
        ):
            continue
        episodes.append(record)

    def asof(mint, at):
        candidates = [
            b
            for b in bars
            if b.mint == mint and b.close_at <= at and b.available_at <= at and b.close_usd > 0
        ]
        return max(candidates, key=lambda b: b.close_at) if candidates else None

    def forward(mint, at):
        candidates = [
            b
            for b in bars
            if b.mint == mint
            and b.close_at >= at
            and b.available_at >= b.close_at
            and b.close_usd > 0
        ]
        return min(candidates, key=lambda b: b.close_at) if candidates else None

    horizon_results = {}
    for horizon in horizons_minutes:
        returns: list[Decimal] = []
        groups: dict[str, list[Decimal]] = {}
        for episode in episodes:
            source, destination = episode.pair.split(":", 1)
            entry_a, entry_b = asof(source, episode.at), asof(destination, episode.at)
            target = episode.at + timedelta(minutes=horizon)
            exit_a, exit_b = forward(source, target), forward(destination, target)
            if not all((entry_a, entry_b, exit_a, exit_b)):
                continue
            if exit_a.close_at != exit_b.close_at:
                continue  # Stale mismatched observations cannot form a ratio.
            relative = (exit_b.close_usd / entry_b.close_usd) / (
                exit_a.close_usd / entry_a.close_usd
            ) - Decimal(1)
            returns.append(relative)
            groups.setdefault(episode.at.date().isoformat(), []).append(relative)
        mean = sum(returns, Decimal(0)) / len(returns) if returns else None
        interval = None
        if len(returns) >= 10 and len(groups) >= 5:
            rng = random.Random(0)
            keys = sorted(groups)
            means = []
            for _ in range(300):
                sample = [value for _ in keys for value in groups[rng.choice(keys)]]
                means.append(sum(sample, Decimal(0)) / len(sample))
            means.sort()
            interval = [str(means[7]), str(means[292])]
        horizon_results[str(horizon)] = {
            "events_with_outcome": len(returns),
            "mean_relative_return": str(mean) if mean is not None else None,
            "distribution": [str(value) for value in returns],
            "confidence_interval": interval,
            "interval_method": "day-block bootstrap, 300 deterministic resamples"
            if interval
            else "insufficient independent day blocks",
        }
    return {
        "distinct_episodes": len(episodes),
        "horizons": horizon_results,
        "interpretation": "descriptive association, not causality or executable P&L",
    }
