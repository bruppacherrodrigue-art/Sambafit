"""Four deterministic software baselines; never a claim of executable history."""

from datetime import datetime
from decimal import Decimal

from .engine import Rotation
from .paper import simulate_paper
from .replay import DecisionRecord
from .signals import Decision, MarketBar, decide


def _record(at: datetime, pair: str, state: str, reason: str) -> DecisionRecord:
    return DecisionRecord(at, pair, Decision(state, "complete", 0, (), (reason,)))


def compare_variants(
    rotations: list[Rotation],
    bars: list[MarketBar],
    initial_cash: Decimal,
    universe: set[str],
) -> dict[str, dict]:
    """Apply the same reserve policy and quotes to four fixed, unoptimized rules."""
    if initial_cash <= 0 or not universe:
        raise ValueError("positive capital and nonempty fixed universe required")
    ordered = sorted(
        (b for b in bars if b.mint in universe), key=lambda b: (b.available_at, b.close_at, b.mint)
    )
    if not ordered:
        raise ValueError("no visible bars for fixed universe")
    start, end = ordered[0].available_at, ordered[-1].available_at
    late_rotation_count = sum(r.available_at > end for r in rotations)
    first = {}
    for bar in ordered:
        first.setdefault(bar.mint, bar)
    basket = [
        _record(bar.available_at, f"CASH:{mint}", "confirmed", "fixed basket")
        for mint, bar in sorted(first.items())
    ]
    market = []
    previous = {}
    for bar in ordered:
        prior = previous.get(bar.mint)
        if prior is not None:
            if bar.close_usd > prior.close_usd:
                market.append(
                    _record(
                        bar.available_at,
                        f"CASH:{bar.mint}",
                        "confirmed",
                        "positive previous return",
                    )
                )
            elif bar.close_usd < prior.close_usd:
                market.append(
                    _record(
                        bar.available_at,
                        f"CASH:{bar.mint}",
                        "invalidated",
                        "negative previous return",
                    )
                )
        previous[bar.mint] = bar
    eligible = sorted(
        (
            r
            for r in rotations
            if r.source in universe
            and r.destination in universe
            and r.direction == "between_coins"
            and r.available_at <= end
        ),
        key=lambda r: (r.available_at, r.source_op, r.wallet),
    )
    wallets = [
        _record(
            r.available_at, f"{r.source}:{r.destination}", "confirmed", f"{r.evidence} wallet flow"
        )
        for r in eligible
    ]
    combined = []
    for rotation in eligible:
        decision = decide(
            [r for r in eligible if r.available_at <= rotation.available_at],
            ordered,
            rotation.available_at,
            pair=(rotation.source, rotation.destination),
        )
        combined.append(
            DecisionRecord(
                rotation.available_at, f"{rotation.source}:{rotation.destination}", decision
            )
        )
    outputs = {}
    for name, decisions in (
        ("basket", basket),
        ("market_only", market),
        ("wallets_only", wallets),
        ("combined", combined),
    ):
        simulation = simulate_paper(tuple(decisions), ordered, initial_cash)
        filled = [o for o in simulation.orders if o["status"] == "filled"]
        last_prices = {b.mint: b.close_usd for b in ordered}
        equity = simulation.book.cash + sum(
            (
                qty * last_prices[mint]
                for mint, qty in simulation.book.positions.items()
                if mint in last_prices
            ),
            Decimal(0),
        )
        turnover = (
            sum((Decimal(o["quantity"]) * Decimal(o["price"]) for o in filled), Decimal(0))
            / initial_cash
        )
        mark_times = sorted({b.available_at for b in ordered})
        cash = initial_cash
        held: dict[str, Decimal] = {}
        exposure_sum = Decimal(0)
        stable_sum = Decimal(0)
        for at in mark_times:
            for order in filled:
                if order["at"] != at:
                    continue
                qty, price, fee = map(Decimal, (order["quantity"], order["price"], order["fee"]))
                sign = 1 if order["side"] == "buy" else -1
                held[order["mint"]] = held.get(order["mint"], Decimal(0)) + sign * qty
                cash -= sign * qty * price + fee
            marks = {b.mint: b.close_usd for b in ordered if b.available_at <= at}
            invested = sum(
                (qty * marks.get(mint, Decimal(0)) for mint, qty in held.items()), Decimal(0)
            )
            total = cash + invested
            if total > 0:
                exposure_sum += invested / total
                stable_sum += cash / total
        count = Decimal(len(mark_times))
        blocked = all(b.liquidity_usd is None for b in ordered)
        outputs[name] = {
            "initial_cash": str(initial_cash),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "universe": sorted(universe),
            "wallet_events_after_market_end": late_rotation_count,
            "input_alignment": "market_ends_before_wallet_observation"
            if late_rotation_count
            else "aligned_within_observed_period",
            "signals": len(decisions),
            "decision_states": [
                {
                    "pair": record.pair,
                    "state": record.decision.state,
                    "quality": record.decision.quality,
                }
                for record in decisions
            ],
            "filled_orders": len(filled),
            "unfilled_orders": len(simulation.orders) - len(filled),
            "cash": str(simulation.book.cash),
            "holdings": {k: str(v) for k, v in simulation.book.positions.items()},
            "ending_equity": str(equity),
            "net_return": None if blocked else str(equity / initial_cash - 1),
            "fees_usd": str(simulation.book.fees),
            "turnover": str(turnover),
            "mean_exposure": str(exposure_sum / count),
            "mean_stable_fraction": str(stable_sum / count),
            "execution_status": "blocked_missing_liquidity" if blocked else "hypothetical_fills",
        }
    return outputs
