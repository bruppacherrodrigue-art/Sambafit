from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.signals import Decision, MarketBar
from rotation.strategy import (
    ExecutionQuote,
    StrategyPolicy,
    assess_strategy,
    load_strategy_config,
    paper_intent,
    qualify_range,
)

T = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
D = Decimal


def test_config_is_versioned_and_applied_to_both_research_and_strict_strategy():
    value = load_strategy_config("config/strategy-r3-1.json")
    assert value.sha256 and value.version == "r3.1-strategy-hypothesis-1"
    assert value.pair_policy.max_economic_flow_age == timedelta(hours=6)
    assert value.pair_policy.max_observation_delay == timedelta(minutes=15)
    assert value.strategy_policy.range_min_bars == 72


def bars(mint: str, prices: list[str]) -> list[MarketBar]:
    start = T - timedelta(hours=len(prices) - 1)
    return [
        MarketBar(
            mint,
            start + timedelta(hours=i),
            start + timedelta(hours=i),
            D(price),
            D(1000),
            D(100000),
            interval_seconds=3600,
        )
        for i, price in enumerate(prices)
    ]


TEST_POLICY = StrategyPolicy(
    range_min_bars=8,
    range_min_span=timedelta(hours=7),
    range_visit_gap=timedelta(hours=2),
    range_horizon=timedelta(days=1),
    range_max_age=timedelta(hours=2),
)


def test_range_requires_repeated_causal_oscillation_and_rejects_trends_and_breakout():
    oscillating = bars("A", ["10", "12", "11", "10", "12", "11", "10", "12"])
    assert qualify_range(oscillating, "A", T, TEST_POLICY).qualified
    future = bars("A", ["1", "2", "3", "4", "5", "6", "7", "8"])
    assert not qualify_range(future, "A", T, TEST_POLICY).qualified
    assert not qualify_range(
        bars("A", ["8", "7", "6", "5", "4", "3", "2", "1"]), "A", T, TEST_POLICY
    ).qualified
    plateau = bars("A", ["10", "12", "12", "12", "12", "12", "12", "12"])
    assert "range_recurrent_visits_missing" in qualify_range(plateau, "A", T, TEST_POLICY).reasons
    breakout = bars("A", ["10", "12", "11", "10", "12", "11", "10", "15"])
    assert "range_breakout" in qualify_range(breakout, "A", T, TEST_POLICY).reasons
    hidden_future = MarketBar(
        "A",
        T + timedelta(hours=1),
        T + timedelta(hours=1),
        D(1000),
        D(1000),
        D(100000),
        interval_seconds=3600,
    )
    assert qualify_range(oscillating + [hidden_future], "A", T, TEST_POLICY) == qualify_range(
        oscillating, "A", T, TEST_POLICY
    )


def test_research_candidate_and_unknown_wallet_proofs_block_strategy_and_execution():
    market = bars("A", ["10", "12", "11", "10", "12", "11", "10", "12"]) + bars(
        "B", ["10", "12", "11", "10", "12", "11", "10", "12"]
    )
    registry = {
        mint: {
            "network": "solana",
            "category": "memecoin",
            "role": "target",
            "status": "research_candidate",
            "known_at": T.isoformat(),
        }
        for mint in ("A", "B")
    }
    decision = Decision("candidate", "complete", 60, (), ())
    result = assess_strategy(
        "A",
        "B",
        decision,
        market,
        T,
        registry,
        cohort={"wallets": [], "cohort_known_at": T.isoformat()},
        policy=TEST_POLICY,
    )
    assert result.research_state == "candidate"
    assert result.admission == "blocked"
    assert "A_not_admitted" in result.reasons
    assert "qualified_directional_wallet_missing" in result.reasons
    assert result.paper_status == "blocked"


def test_admission_needs_dated_assets_and_repeated_directional_wallet_evidence():
    market = bars("A", ["10", "12", "11", "10", "12", "11", "12", "11.5"]) + bars(
        "B", ["10", "12", "11", "10", "12", "11", "10", "10.5"]
    )
    proof_at = (T - timedelta(days=30)).isoformat()
    registry = {
        mint: {
            "network": "solana",
            "category": "memecoin",
            "role": "target",
            "status": "admitted",
            "known_at": proof_at,
            "classification_proof_at": proof_at,
            "liquidity_proof_at": proof_at,
            "coverage_proof_at": proof_at,
            "community_review_at": proof_at,
            "community_review_status": "approved",
            "age_days_verified": 90,
            "liquidity_usd_verified": "100000",
        }
        for mint in ("A", "B")
    }
    cohort = {
        "cohort_known_at": (T - timedelta(days=1)).isoformat(),
        "wallets": [
            {
                "wallet": "wallet",
                "attributed_between_memecoins_usd": "12000",
                "distinct_reallocation_days": 3,
                "coverage_started_at": (T - timedelta(days=10)).isoformat(),
                "coverage_ended_at": (T - timedelta(days=1)).isoformat(),
                "directional_status": "qualified",
                "independence_status": "independent",
            }
        ],
    }
    cohort["wallets"].append({**cohort["wallets"][0], "wallet": "wallet2"})
    decision = Decision(
        "candidate", "complete", 60, (), (), metrics=(("evidence_wallets", "wallet,wallet2"),)
    )
    assert (
        assess_strategy("A", "B", decision, market, T, registry, cohort, TEST_POLICY).admission
        == "admitted"
    )
    a_low = bars("A", ["10", "12", "11", "10", "12", "11", "12", "10.5"])
    assert (
        "A_not_high_in_qualified_range"
        in assess_strategy(
            "A",
            "B",
            decision,
            a_low + [bar for bar in market if bar.mint == "B"],
            T,
            registry,
            cohort,
            TEST_POLICY,
        ).reasons
    )
    b_high = bars("B", ["10", "12", "11", "10", "12", "11", "10", "11.5"])
    assert (
        "B_not_low_in_qualified_range"
        in assess_strategy(
            "A",
            "B",
            decision,
            [bar for bar in market if bar.mint == "A"] + b_high,
            T,
            registry,
            cohort,
            TEST_POLICY,
        ).reasons
    )
    linked = {
        **cohort,
        "wallets": [{**row, "linked_group": "same_actor"} for row in cohort["wallets"]],
    }
    assert (
        "independent_wallet_confirmation_missing"
        in assess_strategy("A", "B", decision, market, T, registry, linked, TEST_POLICY).reasons
    )
    future_cohort = {**cohort, "cohort_known_at": (T + timedelta(minutes=1)).isoformat()}
    assert (
        assess_strategy(
            "A", "B", decision, market, T, registry, future_cohort, TEST_POLICY
        ).admission
        == "blocked"
    )


def test_paper_intent_requires_two_quotes_depth_and_known_costs():
    missing = paper_intent(
        "A",
        "B",
        T,
        capital=D(1000),
        source_quantity=D(100),
        target_usd=D(14),
        invalidation_usd=D(9),
        source_quote=None,
        destination_quote=None,
        policy=TEST_POLICY,
    )
    assert missing.status == "blocked" and "missing_executable_quote" in missing.reasons
    source = ExecutionQuote(
        "A", "sell", D(10), D(100), D(100000), D(1), D(1), D(0), D(0), T, T + timedelta(minutes=1)
    )
    dest = ExecutionQuote(
        "B", "buy", D(10), D(100), D(100000), D(1), D(1), D(0), D(0), T, T + timedelta(minutes=1)
    )
    ready = paper_intent(
        "A",
        "B",
        T,
        capital=D(1000),
        source_quantity=D(100),
        target_usd=D(14),
        invalidation_usd=D(9),
        source_quote=source,
        destination_quote=dest,
        policy=TEST_POLICY,
    )
    assert ready.status == "paper_intent"
    assert ready.size_usd is not None and ready.size_usd <= D(100)
    assert ready.reward_risk is not None and ready.reward_risk > D(1)
    no_depth = ExecutionQuote(
        "B", "buy", D(10), D(100), None, D(1), D(1), D(0), D(0), T, T + timedelta(minutes=1)
    )
    assert (
        "B_depth_missing_or_low"
        in paper_intent(
            "A",
            "B",
            T,
            capital=D(1000),
            source_quantity=D(100),
            target_usd=D(14),
            invalidation_usd=D(9),
            source_quote=source,
            destination_quote=no_depth,
            policy=TEST_POLICY,
        ).reasons
    )
    unknown_fee = ExecutionQuote(
        "B", "buy", D(10), D(100), D(100000), None, D(1), D(0), D(0), T, T + timedelta(minutes=1)
    )
    assert (
        "B_cost_unknown"
        in paper_intent(
            "A",
            "B",
            T,
            capital=D(1000),
            source_quantity=D(100),
            target_usd=D(14),
            invalidation_usd=D(9),
            source_quote=source,
            destination_quote=unknown_fee,
            policy=TEST_POLICY,
        ).reasons
    )
