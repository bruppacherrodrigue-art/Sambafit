"""One persistent budget shared by all R2 source calls and process sessions."""

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class R2BudgetExceeded(RuntimeError):
    pass


class R2Budget:
    def __init__(
        self,
        path: str | Path,
        *,
        max_calls: int = 2000,
        max_active_seconds: int = 1800,
        now: Callable[[], datetime] | None = None,
    ):
        if not 1 <= max_calls <= 2000 or not 1 <= max_active_seconds <= 1800:
            raise ValueError("R2 global limits exceed authorization")
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.limits = {"max_calls": max_calls, "max_active_seconds": max_active_seconds}
        with self._state() as state:
            if state:
                if state["limits"] != self.limits:
                    raise ValueError("cannot change global limits after budget creation")
            else:
                state.update(
                    limits=self.limits,
                    created_at=self.now().isoformat(),
                    calls_used=0,
                    active_seconds=0.0,
                    attempts=[],
                    sessions=[],
                    active_session=None,
                    phase_limits={},
                )
            state.setdefault("phase_limits", {})

    @contextmanager
    def _state(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else {}
            try:
                yield state
            finally:
                temp = self.path.with_suffix(self.path.suffix + ".tmp")
                temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
                os.replace(temp, self.path)
                fcntl.flock(lock, fcntl.LOCK_UN)

    def snapshot(self) -> dict:
        with self._state() as state:
            return json.loads(json.dumps(state))

    def session(
        self,
        label: str,
        *,
        max_calls: int,
        max_seconds: int,
        phase: str | None = None,
        phase_max_calls: int | None = None,
        phase_max_active_seconds: int | None = None,
    ):
        if not 1 <= max_calls <= self.limits["max_calls"] or not 1 <= max_seconds <= 1800:
            raise ValueError("invalid session limits")
        if phase and (
            not phase_max_calls
            or not phase_max_active_seconds
            or phase_max_calls > self.limits["max_calls"]
            or phase_max_active_seconds > self.limits["max_active_seconds"]
        ):
            raise ValueError("invalid persistent phase limits")
        if not phase and (phase_max_calls or phase_max_active_seconds):
            raise ValueError("phase name required for phase limits")
        return _R2Session(
            self, label, max_calls, max_seconds, phase, phase_max_calls, phase_max_active_seconds
        )


class _R2Session:
    def __init__(
        self,
        budget: R2Budget,
        label: str,
        max_calls: int,
        max_seconds: int,
        phase: str | None,
        phase_max_calls: int | None,
        phase_max_active_seconds: int | None,
    ):
        self.budget = budget
        self.label = label
        self.max_calls = max_calls
        self.max_seconds = max_seconds
        self.id = uuid.uuid4().hex
        self.phase = phase
        self.phase_limits = (
            {"max_calls": phase_max_calls, "max_active_seconds": phase_max_active_seconds}
            if phase
            else None
        )

    def __enter__(self):
        with self.budget._state() as state:
            if self.phase:
                prior_limits = state["phase_limits"].get(self.phase)
                if prior_limits and prior_limits != self.phase_limits:
                    raise ValueError("cannot change phase limits after phase creation")
                state["phase_limits"][self.phase] = self.phase_limits
            previous = state["active_session"]
            if previous:
                try:
                    os.kill(previous["pid"], 0)
                except ProcessLookupError:
                    # An in-flight HTTP request may have finished just before a crash.
                    # Charge its maximum 30-second tail rather than erasing elapsed time.
                    state["active_seconds"] += 30
                    previous["active_seconds"] = previous.get("active_seconds", 0) + 30
                    previous["status"] = "interrupted"
                    state["sessions"].append(previous)
                else:
                    raise R2BudgetExceeded("another collection session is active")
            if state["active_seconds"] >= self.budget.limits["max_active_seconds"]:
                raise R2BudgetExceeded("global active time limit reached")
            now = self.budget.now().isoformat()
            state["active_session"] = {
                "id": self.id,
                "label": self.label,
                "pid": os.getpid(),
                "started_at": now,
                "last_tick": now,
                "max_calls": self.max_calls,
                "max_seconds": self.max_seconds,
                "calls_used": 0,
                "active_seconds": 0.0,
                "phase": self.phase,
                "status": "running",
            }
        return self

    def _tick(self, state: dict) -> dict:
        session = state["active_session"]
        if not session or session["id"] != self.id:
            raise R2BudgetExceeded("R2 session is not active")
        now = self.budget.now()
        last = datetime.fromisoformat(session["last_tick"])
        elapsed = max(0.0, (now - last).total_seconds())
        state["active_seconds"] += elapsed
        session["active_seconds"] += elapsed
        session["last_tick"] = now.isoformat()
        return session

    def reserve(self, source: str, request: str) -> int:
        with self.budget._state() as state:
            session = self._tick(state)
            if os.getenv("ROTATION_KILL_SWITCH") == "1":
                raise R2BudgetExceeded("kill switch active")
            if state["active_seconds"] >= self.budget.limits["max_active_seconds"]:
                raise R2BudgetExceeded("global active time limit reached")
            if (
                self.budget.now() - datetime.fromisoformat(session["started_at"])
            ).total_seconds() >= self.max_seconds:
                raise R2BudgetExceeded("session active time limit reached")
            if state["calls_used"] >= self.budget.limits["max_calls"]:
                raise R2BudgetExceeded("global call limit reached")
            if self.phase:
                used_calls = session["calls_used"] + sum(
                    s["calls_used"] for s in state["sessions"] if s.get("phase") == self.phase
                )
                used_seconds = session["active_seconds"] + sum(
                    s.get("active_seconds", 0)
                    for s in state["sessions"]
                    if s.get("phase") == self.phase
                )
                if (
                    used_calls >= self.phase_limits["max_calls"]
                    or used_seconds >= self.phase_limits["max_active_seconds"]
                ):
                    raise R2BudgetExceeded("persistent phase limit reached")
            if session["calls_used"] >= self.max_calls:
                raise R2BudgetExceeded("session call limit reached")
            state["calls_used"] += 1
            session["calls_used"] += 1
            number = state["calls_used"]
            state["attempts"].append(
                {
                    "number": number,
                    "session_id": self.id,
                    "at": self.budget.now().isoformat(),
                    "source": source,
                    "request": request,
                    "status": "attempted",
                }
            )
            return number

    def remaining_seconds(self) -> float:
        """Maximum wall time available to the next sleep and request together."""
        with self.budget._state() as state:
            session = self._tick(state)
            now = self.budget.now()
            remaining = [
                self.budget.limits["max_active_seconds"] - state["active_seconds"],
                self.max_seconds
                - (now - datetime.fromisoformat(session["started_at"])).total_seconds(),
            ]
            if self.phase:
                previous = sum(
                    item.get("active_seconds", 0)
                    for item in state["sessions"]
                    if item.get("phase") == self.phase
                )
                remaining.append(
                    self.phase_limits["max_active_seconds"] - previous - session["active_seconds"]
                )
            return max(0.0, min(remaining))

    def complete(self, number: int, *, status: str, response_hash: str | None = None):
        with self.budget._state() as state:
            attempt = next(
                (
                    a
                    for a in state["attempts"]
                    if a["number"] == number and a["session_id"] == self.id
                ),
                None,
            )
            if attempt is None:
                raise ValueError("unknown R2 attempt")
            attempt["status"] = status
            attempt["response_hash"] = response_hash

    def __exit__(self, exc_type, exc, traceback):
        with self.budget._state() as state:
            session = self._tick(state)
            session["status"] = "completed" if exc_type is None else "stopped_with_error"
            session["ended_at"] = self.budget.now().isoformat()
            state["sessions"].append(session)
            state["active_session"] = None
        return False
