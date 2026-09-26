from datetime import datetime, timedelta, timezone

import pytest

from rotation.pilot import BudgetExceeded, PilotBudget
from rotation.solana import SolanaRpc

T = datetime(2026, 9, 26, 8, tzinfo=timezone.utc)


def test_budget_persists_attempts_before_request_and_resumes_without_reset(tmp_path):
    state = tmp_path / "budget.json"
    first = PilotBudget(state, max_calls=2, max_transactions=1, max_minutes=15, now=lambda: T)
    first.reserve("gecko")
    first.reserve("rpc", signature="signature-1")
    resumed = PilotBudget(
        state, max_calls=2, max_transactions=1, max_minutes=15, now=lambda: T + timedelta(minutes=1)
    )
    assert resumed.calls_used == 2
    assert resumed.unique_transactions == 1
    assert resumed.by_source == {"gecko": 1, "rpc": 1}
    with pytest.raises(BudgetExceeded, match="call limit"):
        resumed.reserve("gecko")


def test_budget_rejects_second_unique_transaction_and_expired_run(tmp_path):
    state = tmp_path / "budget.json"
    current = T
    budget = PilotBudget(
        state, max_calls=4, max_transactions=1, max_minutes=15, now=lambda: current
    )
    budget.reserve("rpc", signature="signature-1")
    with pytest.raises(BudgetExceeded, match="transaction limit"):
        budget.reserve("rpc", signature="signature-2")
    assert budget.calls_used == 1
    current += timedelta(minutes=16)
    with pytest.raises(BudgetExceeded, match="time limit"):
        budget.reserve("rpc", signature="signature-1")
    assert budget.calls_used == 1


def test_rpc_shares_persistent_budget_and_counts_failed_attempt(tmp_path):
    class FailingClient:
        def post(self, url, json):
            raise RuntimeError("network unavailable")

    budget = PilotBudget(tmp_path / "budget.json", max_calls=2, max_transactions=1, now=lambda: T)
    rpc = SolanaRpc("https://api.mainnet.solana.com", client=FailingClient(), budget=budget)
    with pytest.raises(RuntimeError, match="network unavailable"):
        rpc.transaction("signature-1")
    assert budget.calls_used == 1 and budget.unique_transactions == 1
