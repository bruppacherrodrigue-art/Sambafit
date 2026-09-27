import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rotation.paper import PaperBook
from rotation.signals import Decision
from rotation.strategy import (
    ExecutionQuote,
    PaperCycle,
    RangeEvidence,
    StrategyAssessment,
    StrategyPolicy,
)

T = datetime(2026, 9, 27, tzinfo=timezone.utc)
D = Decimal
POLICY = StrategyPolicy(
    max_position_fraction=D(1), max_risk_fraction=D("0.1"), min_reward_risk=D(1)
)


def assessment(admission: str = "admitted") -> StrategyAssessment:
    a = RangeEvidence(True, (), D(8), D(12), 2, 2, 72)
    b = RangeEvidence(True, (), D(9), D(14), 2, 2, 72)
    return StrategyAssessment(
        "r3.1-strategy-hypothesis-1", "candidate", admission, "blocked", (), a, b, ("w1", "w2")
    )


def quote(mint: str, side: str, fillable: bool = True) -> ExecutionQuote:
    return ExecutionQuote(
        mint,
        side,
        D(10),
        D(100),
        D(100000),
        D("0.1"),
        D("0.1"),
        D(0),
        D(0),
        T,
        T + timedelta(minutes=1),
        fillable=fillable,
    )


def test_paper_cycle_waits_without_convergence_and_preserves_source_position():
    book = PaperBook(D(0), {"A": D(10)})
    cycle = PaperCycle(book, POLICY)
    event = cycle.apply(
        "A:B",
        Decision("observing", "complete", 0, (), ()),
        assessment("blocked"),
        T,
        quote("A", "sell"),
        quote("B", "buy"),
    )
    assert event["status"] == "wait"
    assert book.positions == {"A": D(10)} and book.cash == 0


def test_paper_cycle_sale_filled_buy_failed_keeps_cash_and_deduplicates(tmp_path):
    book = PaperBook(D(0), {"A": D(10)})
    cycle = PaperCycle(book, POLICY)
    decision = Decision("candidate", "complete", 60, (), ())
    event = cycle.apply(
        "A:B", decision, assessment(), T, quote("A", "sell"), quote("B", "buy", fillable=False)
    )
    assert event["status"] == "buy_unfilled"
    assert D(0) < book.positions["A"] < D(10)
    assert "B" not in book.positions and book.cash > 0
    snapshot = (book.cash, dict(book.positions), dict(book.orders))
    assert (
        cycle.apply(
            "A:B", decision, assessment(), T, quote("A", "sell"), quote("B", "buy", fillable=False)
        )
        == event
    )
    assert (book.cash, book.positions, book.orders) == snapshot
    restarted = PaperCycle.from_snapshot(json.loads(json.dumps(cycle.snapshot())), POLICY)
    assert (
        restarted.apply(
            "A:B", decision, assessment(), T, quote("A", "sell"), quote("B", "buy", fillable=False)
        )
        == event
    )
    assert restarted.book.cash == book.cash
    assert restarted.book.positions == book.positions
    cycle.save(tmp_path / "paper-cycle.json")
    assert PaperCycle.load(tmp_path / "paper-cycle.json", POLICY).snapshot() == cycle.snapshot()


def test_paper_cycle_entry_exit_and_reentry_renew_reference():
    book = PaperBook(D(0), {"A": D(10)})
    cycle = PaperCycle(book, POLICY)
    candidate = Decision("candidate", "complete", 60, (), ())
    first = cycle.apply("A:B", candidate, assessment(), T, quote("A", "sell"), quote("B", "buy"))
    assert first["status"] == "holding_B" and book.positions["B"] > 0
    entry = cycle.entry_reference["A:B"]
    closed = cycle.apply(
        "A:B",
        Decision("invalidated", "complete", 0, (), ()),
        assessment("blocked"),
        T + timedelta(minutes=1),
        None,
        None,
        exit_quote=quote("B", "sell"),
    )
    assert closed["status"] == "stable_reserve" and "B" not in book.positions
    assert "A:B" not in cycle.entry_reference and book.cash > 0
    again = cycle.apply(
        "A:B",
        candidate,
        assessment(),
        T + timedelta(minutes=2),
        ExecutionQuote(
            "A",
            "sell",
            D(11),
            D(100),
            D(100000),
            D(0),
            D(0),
            D(0),
            D(0),
            T + timedelta(minutes=2),
            T + timedelta(minutes=3),
        ),
        ExecutionQuote(
            "B",
            "buy",
            D(11),
            D(100),
            D(100000),
            D(0),
            D(0),
            D(0),
            D(0),
            T + timedelta(minutes=2),
            T + timedelta(minutes=3),
        ),
    )
    assert again["status"] == "holding_B"
    assert cycle.entry_reference["A:B"] != entry
