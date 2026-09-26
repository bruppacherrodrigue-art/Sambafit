from datetime import datetime, timedelta, timezone

import pytest

from rotation.r2_budget import R2Budget, R2BudgetExceeded

T = datetime(2026, 9, 26, 9, tzinfo=timezone.utc)


def test_shared_budget_counts_attempts_across_sessions_and_refuses_reset(tmp_path):
    now = [T]
    path = tmp_path / "shared.json"
    first = R2Budget(path, max_calls=3, max_active_seconds=50, now=lambda: now[0])
    with first.session("discovery", max_calls=2, max_seconds=20) as session:
        request = session.reserve("gecko", "GET /pools")
        session.complete(request, status="http_429")
        now[0] += timedelta(seconds=8)
        session.reserve("gecko", "GET /tokens")
        with pytest.raises(R2BudgetExceeded, match="session call limit"):
            session.reserve("gecko", "GET /third")
    second = R2Budget(path, max_calls=3, max_active_seconds=50, now=lambda: now[0])
    with second.session("market", max_calls=2, max_seconds=20) as session:
        session.reserve("gecko", "GET /ohlcv")
        with pytest.raises(R2BudgetExceeded, match="global call limit"):
            session.reserve("gecko", "GET /again")
    assert second.snapshot()["calls_used"] == 3
    assert second.snapshot()["attempts"][0]["status"] == "http_429"
    with pytest.raises(ValueError, match="cannot change global limits"):
        R2Budget(path, max_calls=4, max_active_seconds=50, now=lambda: now[0])


def test_active_seconds_accumulate_and_expiration_survives_restart(tmp_path):
    now = [T]
    path = tmp_path / "shared.json"
    budget = R2Budget(path, max_calls=10, max_active_seconds=12, now=lambda: now[0])
    with budget.session("first", max_calls=5, max_seconds=10) as session:
        session.reserve("rpc", "getTransaction:abc")
        now[0] += timedelta(seconds=7)
    resumed = R2Budget(path, max_calls=10, max_active_seconds=12, now=lambda: now[0])
    with resumed.session("second", max_calls=5, max_seconds=10) as session:
        now[0] += timedelta(seconds=6)
        with pytest.raises(R2BudgetExceeded, match="global active time"):
            session.reserve("rpc", "getTransaction:def")
    assert resumed.snapshot()["calls_used"] == 1
    assert resumed.snapshot()["active_seconds"] >= 12


def test_rejected_request_persists_elapsed_time_before_process_can_crash(tmp_path):
    now = [T]
    path = tmp_path / "shared.json"
    budget = R2Budget(path, max_calls=10, max_active_seconds=5, now=lambda: now[0])
    with budget.session("audit", max_calls=10, max_seconds=10) as session:
        now[0] += timedelta(seconds=6)
        with pytest.raises(R2BudgetExceeded, match="global active time"):
            session.reserve("rpc", "getTransaction:abc")
        assert (
            R2Budget(path, max_calls=10, max_active_seconds=5, now=lambda: now[0]).snapshot()[
                "active_seconds"
            ]
            >= 6
        )


def test_phase_limits_persist_across_multiple_commands(tmp_path):
    now = [T]
    path = tmp_path / "shared.json"
    budget = R2Budget(path, max_calls=20, max_active_seconds=100, now=lambda: now[0])
    options = {
        "max_calls": 10,
        "max_seconds": 20,
        "phase": "first_audit",
        "phase_max_calls": 2,
        "phase_max_active_seconds": 9,
    }
    with budget.session("discover", **options) as session:
        session.reserve("gecko", "first")
        now[0] += timedelta(seconds=4)
    with budget.session("market", **options) as session:
        session.reserve("gecko", "second")
        with pytest.raises(R2BudgetExceeded, match="persistent phase limit"):
            session.reserve("gecko", "third")
    assert budget.snapshot()["calls_used"] == 2
    with pytest.raises(ValueError, match="cannot change phase limits"):
        with budget.session(
            "retry",
            max_calls=10,
            max_seconds=20,
            phase="first_audit",
            phase_max_calls=3,
            phase_max_active_seconds=9,
        ):
            pass

    with budget.session(
        "phase_time_1",
        max_calls=10,
        max_seconds=20,
        phase="time_only",
        phase_max_calls=10,
        phase_max_active_seconds=5,
    ) as session:
        session.reserve("rpc", "one")
        now[0] += timedelta(seconds=3)
    with budget.session(
        "phase_time_2",
        max_calls=10,
        max_seconds=20,
        phase="time_only",
        phase_max_calls=10,
        phase_max_active_seconds=5,
    ) as session:
        now[0] += timedelta(seconds=3)
        with pytest.raises(R2BudgetExceeded, match="persistent phase limit"):
            session.reserve("rpc", "two")
