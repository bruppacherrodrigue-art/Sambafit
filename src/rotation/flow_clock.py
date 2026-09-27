"""Economic age and evidence latency are different clocks."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FlowClock:
    economic_age: timedelta
    observation_delay: timedelta
    reasons: tuple[str, ...]


def assess_flow_clock(
    economic_at: datetime,
    available_at: datetime,
    decision_at: datetime,
    *,
    max_economic_age: timedelta,
    max_observation_delay: timedelta,
) -> FlowClock:
    if any(value.tzinfo is None for value in (economic_at, available_at, decision_at)):
        raise ValueError("timezone-aware flow clocks required")
    age = decision_at - economic_at
    delay = available_at - economic_at
    reasons = []
    if economic_at > available_at or economic_at > decision_at:
        reasons.append("incoherent_or_future_economic_clock")
    if available_at > decision_at:
        reasons.append("evidence_not_yet_available")
    if age > max_economic_age:
        reasons.append("economic_flow_stale")
    if delay > max_observation_delay:
        reasons.append("observation_delay_excessive")
    return FlowClock(age, delay, tuple(reasons))
