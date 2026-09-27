"""Versioned, causal admission and paper intent for the user's A→B strategy.

Research decisions remain observable even when stricter strategy evidence is missing.
This module has no signing, broadcasting, network access, or real order interface.
"""

import json
import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from .paper import PaperBook
from .signals import Decision, MarketBar, PairPolicy

STRATEGY_VERSION = "r3.1-strategy-hypothesis-1"


@dataclass(frozen=True)
class StrategyPolicy:
    range_horizon: timedelta = timedelta(days=7)
    range_min_bars: int = 72
    range_min_span: timedelta = timedelta(days=3)
    range_max_age: timedelta = timedelta(hours=2)
    range_min_amplitude: Decimal = Decimal("0.10")
    range_zone_fraction: Decimal = Decimal("0.20")
    range_min_visits: int = 2
    range_visit_gap: timedelta = timedelta(hours=6)
    range_breakout_fraction: Decimal = Decimal("0.05")
    source_high_fraction: Decimal = Decimal("0.65")
    destination_low_fraction: Decimal = Decimal("0.45")
    min_wallet_reallocated_usd: Decimal = Decimal("10000")
    min_wallet_distinct_days: int = 3
    min_wallet_coverage: timedelta = timedelta(days=7)
    min_independent_wallets: int = 2
    max_position_fraction: Decimal = Decimal("0.10")
    max_risk_fraction: Decimal = Decimal("0.01")
    min_reward_risk: Decimal = Decimal("1.5")
    min_depth_multiple: Decimal = Decimal("10")
    max_quote_age: timedelta = timedelta(minutes=1)


@dataclass(frozen=True)
class StrategyConfig:
    version: str
    sha256: str
    pair_policy: PairPolicy
    strategy_policy: StrategyPolicy


def load_strategy_config(path: str | Path) -> StrategyConfig:
    raw = Path(path).read_bytes()
    payload = json.loads(raw)
    if payload["version"] != STRATEGY_VERSION:
        raise ValueError("unsupported strategy configuration version")

    def apply(base, values):
        names = {item.name for item in fields(base)}
        converted = {}
        for key, value in values.items():
            field_name = key.removesuffix("_seconds") if key.endswith("_seconds") else key
            if field_name not in names:
                raise ValueError(f"unknown strategy parameter: {key}")
            previous = getattr(base, field_name)
            if isinstance(previous, timedelta):
                if not key.endswith("_seconds"):
                    raise ValueError(f"duration needs seconds: {key}")
                converted[field_name] = timedelta(seconds=int(value))
            elif isinstance(previous, Decimal):
                converted[field_name] = Decimal(str(value))
            elif isinstance(previous, int):
                converted[field_name] = int(value)
            else:
                raise ValueError(f"unsupported parameter: {key}")
        return type(base)(**{**base.__dict__, **converted})

    return StrategyConfig(
        payload["version"],
        sha256(raw).hexdigest(),
        apply(PairPolicy(), payload["pair_policy"]),
        apply(StrategyPolicy(), payload["strategy_policy"]),
    )


@dataclass(frozen=True)
class RangeEvidence:
    qualified: bool
    reasons: tuple[str, ...]
    low: Decimal | None
    high: Decimal | None
    low_visits: int
    high_visits: int
    observations: int
    last_price: Decimal | None = None


@dataclass(frozen=True)
class StrategyAssessment:
    version: str
    research_state: str
    admission: str
    paper_status: str
    reasons: tuple[str, ...]
    source_range: RangeEvidence
    destination_range: RangeEvidence
    qualified_wallets: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionQuote:
    mint: str
    side: str
    executable_price_usd: Decimal
    input_size_usd: Decimal
    depth_usd: Decimal | None
    swap_fee_usd: Decimal | None
    network_fee_usd: Decimal | None
    impact_usd: Decimal | None
    slippage_usd: Decimal | None
    observed_at: datetime
    expires_at: datetime
    # Price may include spread/impact; those components must not be added twice.
    spread_in_price: bool = True
    impact_in_price: bool = True
    fillable: bool = True  # Synthetic outcome only; a real quote gives no fill guarantee.


@dataclass(frozen=True)
class PaperIntent:
    status: str
    reasons: tuple[str, ...]
    size_usd: Decimal | None
    reward_risk: Decimal | None
    target_usd: Decimal | None
    invalidation_usd: Decimal | None


def _visits(
    rows: list[MarketBar], bound: Decimal, opposite: Decimal, *, high: bool, gap: timedelta
) -> int:
    count = 0
    last = None
    armed = True
    for bar in rows:
        inside = bar.close_usd >= bound if high else bar.close_usd <= bound
        crossed_opposite = bar.close_usd <= opposite if high else bar.close_usd >= opposite
        if crossed_opposite:
            armed = True
        if inside and armed and (last is None or bar.close_at - last >= gap):
            count += 1
            last = bar.close_at
            armed = False
    return count


def qualify_range(
    bars: list[MarketBar], mint: str, at: datetime, policy: StrategyPolicy = StrategyPolicy()
) -> RangeEvidence:
    """A range needs repeated separate visits; a monotone trend does not qualify."""
    rows = sorted(
        (
            bar
            for bar in bars
            if bar.mint == mint
            and bar.available_at <= at
            and bar.close_at <= at
            and at - bar.close_at <= policy.range_horizon
            and bar.close_usd > 0
        ),
        key=lambda bar: (bar.close_at, bar.available_at),
    )
    latest = {bar.close_at: bar for bar in rows}
    rows = [latest[key] for key in sorted(latest)]
    reasons = []
    if len(rows) < policy.range_min_bars:
        reasons.append("range_observations_insufficient")
    if not rows:
        return RangeEvidence(False, tuple(reasons), None, None, 0, 0, 0)
    if rows[-1].close_at - rows[0].close_at < policy.range_min_span:
        reasons.append("range_span_insufficient")
    if at - rows[-1].close_at > policy.range_max_age:
        reasons.append("range_stale")
    intervals = {row.interval_seconds for row in rows}
    if len(intervals) != 1 or any(
        current.close_at - previous.close_at != timedelta(seconds=current.interval_seconds)
        for previous, current in zip(rows, rows[1:])
    ):
        reasons.append("range_interval_gap_or_mismatch")
    low = min(row.close_usd for row in rows)
    high = max(row.close_usd for row in rows)
    amplitude = high / low - 1
    if amplitude < policy.range_min_amplitude:
        reasons.append("range_amplitude_insufficient")
    lower_zone = low + (high - low) * policy.range_zone_fraction
    upper_zone = high - (high - low) * policy.range_zone_fraction
    low_visits = _visits(rows, lower_zone, upper_zone, high=False, gap=policy.range_visit_gap)
    high_visits = _visits(rows, upper_zone, lower_zone, high=True, gap=policy.range_visit_gap)
    if low_visits < policy.range_min_visits or high_visits < policy.range_min_visits:
        reasons.append("range_recurrent_visits_missing")
    if len(rows) > 1:
        prior_low = min(row.close_usd for row in rows[:-1])
        prior_high = max(row.close_usd for row in rows[:-1])
        if rows[-1].close_usd < prior_low * (1 - policy.range_breakout_fraction) or rows[
            -1
        ].close_usd > prior_high * (1 + policy.range_breakout_fraction):
            reasons.append("range_breakout")
    return RangeEvidence(
        not reasons,
        tuple(reasons),
        low,
        high,
        low_visits,
        high_visits,
        len(rows),
        rows[-1].close_usd,
    )


def _asset_admission(mint: str, at: datetime, registry: dict[str, dict]) -> tuple[str, ...]:
    row = registry.get(mint)
    if row is None:
        return (f"{mint}_classification_unknown",)
    reasons = []
    if (
        row.get("network") != "solana"
        or row.get("category") != "memecoin"
        or row.get("role") != "target"
    ):
        reasons.append(f"{mint}_not_solana_memecoin_target")
    if row.get("status") != "admitted":
        reasons.append(f"{mint}_not_admitted")
    for field in (
        "known_at",
        "classification_proof_at",
        "liquidity_proof_at",
        "coverage_proof_at",
        "community_review_at",
    ):
        value = row.get(field)
        if value is None or datetime.fromisoformat(value) > at:
            reasons.append(f"{mint}_{field}_unavailable")
    if row.get("community_review_status") != "approved":
        reasons.append(f"{mint}_community_review_pending")
    if row.get("age_days_verified") is None or row["age_days_verified"] < 30:
        reasons.append(f"{mint}_durability_unproven")
    if row.get("liquidity_usd_verified") is None or Decimal(
        str(row["liquidity_usd_verified"])
    ) < Decimal("100000"):
        reasons.append(f"{mint}_liquidity_unproven")
    return tuple(reasons)


def _qualified_wallets(cohort: dict, at: datetime, policy: StrategyPolicy) -> tuple[str, ...]:
    known = cohort.get("cohort_known_at")
    if not known or datetime.fromisoformat(known) > at:
        return ()
    result = []
    for row in cohort.get("wallets", []):
        amount = row.get("attributed_between_memecoins_usd")
        start, end = row.get("coverage_started_at"), row.get("coverage_ended_at")
        if (
            amount is None
            or Decimal(amount) < policy.min_wallet_reallocated_usd
            or row.get("distinct_reallocation_days", 0) < policy.min_wallet_distinct_days
            or not start
            or not end
            or datetime.fromisoformat(end) - datetime.fromisoformat(start)
            < policy.min_wallet_coverage
            or datetime.fromisoformat(end) > at
            or row.get("directional_status") != "qualified"
            or row.get("independence_status") not in {"independent", "linked_capped"}
        ):
            continue
        result.append(row["wallet"])
    return tuple(sorted(result))


def assess_strategy(
    source: str,
    destination: str,
    decision: Decision,
    bars: list[MarketBar],
    at: datetime,
    registry: dict[str, dict],
    cohort: dict,
    policy: StrategyPolicy = StrategyPolicy(),
) -> StrategyAssessment:
    source_range = qualify_range(bars, source, at, policy)
    destination_range = qualify_range(bars, destination, at, policy)
    reasons = []
    if source == destination:
        reasons.append("same_mint_not_rotation")
    reasons.extend(_asset_admission(source, at, registry))
    reasons.extend(_asset_admission(destination, at, registry))
    if not source_range.qualified:
        reasons.extend(f"A_{reason}" for reason in source_range.reasons)
    elif (
        source_range.high > source_range.low
        and (source_range.last_price - source_range.low) / (source_range.high - source_range.low)
        < policy.source_high_fraction
    ):
        reasons.append("A_not_high_in_qualified_range")
    if not destination_range.qualified:
        reasons.extend(f"B_{reason}" for reason in destination_range.reasons)
    elif (
        destination_range.high > destination_range.low
        and (destination_range.last_price - destination_range.low)
        / (destination_range.high - destination_range.low)
        > policy.destination_low_fraction
    ):
        reasons.append("B_not_low_in_qualified_range")
    wallets = _qualified_wallets(cohort, at, policy)
    if not wallets:
        reasons.append("qualified_directional_wallet_missing")
    observed_wallets = dict(decision.metrics).get("evidence_wallets") or ""
    contributing = set(observed_wallets.split(",")) if observed_wallets else set()
    # A qualified wallet elsewhere in the cohort cannot validate this pair.
    involved = set(wallets) & contributing
    groups = {
        row.get("linked_group") or row["wallet"]
        for row in cohort.get("wallets", [])
        if row.get("wallet") in involved
    }
    if len(groups) < policy.min_independent_wallets:
        reasons.append("independent_wallet_confirmation_missing")
    if decision.state not in {"candidate", "confirmed"}:
        reasons.append("research_pair_not_ready")
    admission = "blocked" if reasons else "admitted"
    return StrategyAssessment(
        STRATEGY_VERSION,
        decision.state,
        admission,
        "blocked",
        tuple(reasons),
        source_range,
        destination_range,
        tuple(sorted(involved)),
    )


def paper_intent(
    source: str,
    destination: str,
    at: datetime,
    *,
    capital: Decimal,
    source_quantity: Decimal,
    target_usd: Decimal,
    invalidation_usd: Decimal,
    source_quote: ExecutionQuote | None,
    destination_quote: ExecutionQuote | None,
    policy: StrategyPolicy = StrategyPolicy(),
) -> PaperIntent:
    """Plan only; balances change solely in PaperBook after separately verified fills."""
    if not source_quote or not destination_quote:
        return PaperIntent(
            "blocked", ("missing_executable_quote",), None, None, target_usd, invalidation_usd
        )
    reasons = []
    for mint, side, quote in (
        (source, "sell", source_quote),
        (destination, "buy", destination_quote),
    ):
        if (
            quote.mint != mint
            or quote.side != side
            or quote.observed_at > at
            or quote.expires_at < at
            or at - quote.observed_at > policy.max_quote_age
        ):
            reasons.append(f"{mint}_quote_invalid_or_stale")
        if (
            quote.depth_usd is None
            or quote.depth_usd < quote.input_size_usd * policy.min_depth_multiple
        ):
            reasons.append(f"{mint}_depth_missing_or_low")
        if any(
            value is None
            for value in (
                quote.swap_fee_usd,
                quote.network_fee_usd,
                quote.impact_usd,
                quote.slippage_usd,
            )
        ):
            reasons.append(f"{mint}_cost_unknown")
        elif any(
            value < 0
            for value in (
                quote.swap_fee_usd,
                quote.network_fee_usd,
                quote.impact_usd,
                quote.slippage_usd,
            )
        ):
            reasons.append(f"{mint}_cost_invalid")
        if quote.executable_price_usd <= 0 or quote.input_size_usd <= 0:
            reasons.append(f"{mint}_quote_invalid")
    if capital <= 0 or source_quantity <= 0:
        reasons.append("paper_capital_or_source_position_missing")
    if reasons:
        return PaperIntent("blocked", tuple(reasons), None, None, target_usd, invalidation_usd)
    entry = destination_quote.executable_price_usd
    if invalidation_usd >= entry or target_usd <= entry:
        return PaperIntent(
            "blocked",
            ("target_or_invalidation_incoherent",),
            None,
            None,
            target_usd,
            invalidation_usd,
        )
    # Executable prices already include spread and optionally impact. Add only charges
    # outside those prices; fixed costs are prorated at the contemplated size.
    size = min(
        capital * policy.max_position_fraction,
        source_quote.input_size_usd,
        destination_quote.input_size_usd,
        source_quantity * source_quote.executable_price_usd,
    )
    costs = sum(
        (
            quote.swap_fee_usd
            + quote.network_fee_usd
            + quote.slippage_usd
            + (Decimal(0) if quote.impact_in_price else quote.impact_usd)
        )
        for quote in (source_quote, destination_quote)
    )
    source_cost = (
        source_quote.swap_fee_usd
        + source_quote.network_fee_usd
        + source_quote.slippage_usd
        + (Decimal(0) if source_quote.impact_in_price else source_quote.impact_usd)
    )
    if size <= source_cost:
        return PaperIntent(
            "blocked", ("source_proceeds_below_cost",), None, None, target_usd, invalidation_usd
        )
    max_loss_per_usd = (entry - invalidation_usd) / entry + costs / size
    if max_loss_per_usd <= 0:
        return PaperIntent(
            "blocked", ("risk_not_positive",), None, None, target_usd, invalidation_usd
        )
    size = min(size, capital * policy.max_risk_fraction / max_loss_per_usd)
    if size <= 0:
        return PaperIntent(
            "blocked", ("paper_size_zero",), None, None, target_usd, invalidation_usd
        )
    reward = (target_usd - entry) / entry * size - costs
    risk = (entry - invalidation_usd) / entry * size + costs
    ratio = reward / risk if risk > 0 else None
    if ratio is None or ratio < policy.min_reward_risk:
        return PaperIntent(
            "blocked", ("reward_risk_below_hypothesis",), size, ratio, target_usd, invalidation_usd
        )
    return PaperIntent("paper_intent", (), size, ratio, target_usd, invalidation_usd)


class PaperCycle:
    """Explicit paper-only A reduction, B entry, exit and fresh re-entry episodes."""

    def __init__(self, book: PaperBook, policy: StrategyPolicy = StrategyPolicy()):
        self.book = book
        self.policy = policy
        self.processed: dict[str, dict] = {}
        self.entry_reference: dict[str, Decimal] = {}
        self.episodes: dict[str, int] = {}

    def snapshot(self) -> dict:
        return {
            "book": {
                "cash": str(self.book.cash),
                "positions": {mint: str(value) for mint, value in self.book.positions.items()},
                "orders": dict(self.book.orders),
                "fees": str(self.book.fees),
            },
            "processed": dict(self.processed),
            "entry_reference": {pair: str(value) for pair, value in self.entry_reference.items()},
            "episodes": dict(self.episodes),
            "strategy_version": STRATEGY_VERSION,
        }

    def save(self, path: str | Path) -> None:
        """Atomically checkpoint a completed paper transition, never a live order."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(self.snapshot(), sort_keys=True, indent=2) + "\n")
        os.replace(temp, path)

    @classmethod
    def load(cls, path: str | Path, policy: StrategyPolicy = StrategyPolicy()) -> "PaperCycle":
        return cls.from_snapshot(json.loads(Path(path).read_text()), policy)

    @classmethod
    def from_snapshot(
        cls, payload: dict, policy: StrategyPolicy = StrategyPolicy()
    ) -> "PaperCycle":
        if payload.get("strategy_version") != STRATEGY_VERSION:
            raise ValueError("paper snapshot strategy version mismatch")
        raw = payload["book"]
        book = PaperBook(
            Decimal(raw["cash"]),
            {mint: Decimal(value) for mint, value in raw["positions"].items()},
            dict(raw["orders"]),
            Decimal(raw["fees"]),
        )
        cycle = cls(book, policy)
        cycle.processed = dict(payload["processed"])
        cycle.entry_reference = {
            pair: Decimal(value) for pair, value in payload["entry_reference"].items()
        }
        cycle.episodes = {pair: int(value) for pair, value in payload["episodes"].items()}
        return cycle

    @staticmethod
    def _external_fee(quote: ExecutionQuote) -> Decimal:
        return (
            quote.swap_fee_usd
            + quote.network_fee_usd
            + quote.slippage_usd
            + (Decimal(0) if quote.impact_in_price else quote.impact_usd)
        )

    def apply(
        self,
        pair: str,
        decision: Decision,
        assessment: StrategyAssessment,
        at: datetime,
        source_quote: ExecutionQuote | None,
        destination_quote: ExecutionQuote | None,
        *,
        exit_quote: ExecutionQuote | None = None,
    ) -> dict:
        key = sha256(
            json.dumps(
                {"pair": pair, "at": at.isoformat(), "decision": asdict(decision)},
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if key in self.processed:
            return self.processed[key]
        source, destination = pair.split(":", 1)
        if decision.state in {"invalidated", "expired"}:
            quantity = self.book.positions.get(destination, Decimal(0))
            if quantity <= 0:
                self.entry_reference.pop(pair, None)
                event = {
                    "status": "stable_reserve" if self.book.cash > 0 else "wait",
                    "reason": "no_destination_position",
                    "at": at.isoformat(),
                }
            elif (
                exit_quote is None
                or exit_quote.mint != destination
                or exit_quote.side != "sell"
                or exit_quote.observed_at > at
                or exit_quote.expires_at < at
                or at - exit_quote.observed_at > self.policy.max_quote_age
                or any(
                    value is None
                    for value in (
                        exit_quote.swap_fee_usd,
                        exit_quote.network_fee_usd,
                        exit_quote.impact_usd,
                        exit_quote.slippage_usd,
                        exit_quote.depth_usd,
                    )
                )
                or (
                    exit_quote.depth_usd is not None
                    and exit_quote.depth_usd
                    < quantity * exit_quote.executable_price_usd * self.policy.min_depth_multiple
                )
            ):
                return {
                    "status": "exit_pending",
                    "reason": "exit_quote_or_cost_unknown",
                    "at": at.isoformat(),
                }
            else:
                if quantity * exit_quote.executable_price_usd <= self._external_fee(exit_quote):
                    return {
                        "status": "exit_pending",
                        "reason": "exit_proceeds_below_cost",
                        "at": at.isoformat(),
                    }
                order_id = f"{pair}:exit:{self.episodes.get(pair, 0)}:{at.isoformat()}"
                status = self.book.sell(
                    destination,
                    quantity,
                    exit_quote.executable_price_usd,
                    self._external_fee(exit_quote),
                    order_id,
                    executable=exit_quote.fillable,
                )
                if status != "filled":
                    return {
                        "status": "exit_pending",
                        "reason": "paper_exit_unfilled",
                        "at": at.isoformat(),
                    }
                self.entry_reference.pop(pair, None)
                event = {
                    "status": "stable_reserve",
                    "reason": "paper_exit_filled",
                    "at": at.isoformat(),
                    "cash": str(self.book.cash),
                }
            self.processed[key] = event
            return event
        if pair in self.entry_reference:
            event = {"status": "holding_B", "reason": "existing_episode", "at": at.isoformat()}
            self.processed[key] = event
            return event
        if decision.state not in {"candidate", "confirmed"} or assessment.admission != "admitted":
            event = {
                "status": "wait",
                "reason": "strategy_convergence_or_admission_missing",
                "at": at.isoformat(),
            }
            self.processed[key] = event
            return event
        source_quantity = self.book.positions.get(source, Decimal(0))
        if source_quantity <= 0 or source_quote is None or destination_quote is None:
            event = {
                "status": "wait",
                "reason": "source_position_or_quote_missing",
                "at": at.isoformat(),
            }
            self.processed[key] = event
            return event
        target = assessment.destination_range.high
        invalidation = assessment.destination_range.low
        if target is None or invalidation is None:
            event = {"status": "wait", "reason": "destination_range_unknown", "at": at.isoformat()}
            self.processed[key] = event
            return event
        equity = self.book.cash + source_quantity * source_quote.executable_price_usd
        intent = paper_intent(
            source,
            destination,
            at,
            capital=equity,
            source_quantity=source_quantity,
            target_usd=target,
            invalidation_usd=invalidation,
            source_quote=source_quote,
            destination_quote=destination_quote,
            policy=self.policy,
        )
        if intent.status != "paper_intent" or intent.size_usd is None:
            event = {"status": "wait", "reason": ",".join(intent.reasons), "at": at.isoformat()}
            self.processed[key] = event
            return event
        episode = self.episodes.get(pair, 0) + 1
        sale_quantity = min(source_quantity, intent.size_usd / source_quote.executable_price_usd)
        sale_status = self.book.sell(
            source,
            sale_quantity,
            source_quote.executable_price_usd,
            self._external_fee(source_quote),
            f"{pair}:sale:{episode}:{at.isoformat()}",
            executable=source_quote.fillable,
        )
        if sale_status != "filled":
            event = {"status": "wait", "reason": "source_sale_unfilled", "at": at.isoformat()}
        else:
            self.episodes[pair] = episode
            fee = self._external_fee(destination_quote)
            buy_budget = min(self.book.cash, intent.size_usd)
            quantity = (buy_budget - fee) / destination_quote.executable_price_usd
            if quantity <= 0:
                event = {
                    "status": "buy_unfilled",
                    "reason": "sale_cash_below_buy_cost",
                    "at": at.isoformat(),
                    "cash": str(self.book.cash),
                }
            else:
                buy_status = self.book.buy(
                    destination,
                    quantity,
                    destination_quote.executable_price_usd,
                    fee,
                    f"{pair}:buy:{episode}",
                    executable=destination_quote.fillable,
                )
                if buy_status == "filled":
                    self.entry_reference[pair] = destination_quote.executable_price_usd
                    event = {
                        "status": "holding_B",
                        "reason": "paper_rotation_filled",
                        "at": at.isoformat(),
                        "entry_price": str(self.entry_reference[pair]),
                        "target": str(target),
                        "invalidation": str(invalidation),
                        "reward_risk": str(intent.reward_risk),
                    }
                else:
                    event = {
                        "status": "buy_unfilled",
                        "reason": "paper_buy_unfilled_after_sale",
                        "at": at.isoformat(),
                        "cash": str(self.book.cash),
                    }
        self.processed[key] = event
        return event
