# R2 Universe and Cohort Implementation Plan

> **For agentic workers:** Use this plan task by task. The user has already authorized execution of the R2 lot; no additional design approval is required.

**Goal:** Deliver a dated research universe, reproducible candidate cohort, Fomo evidence workflow, and bounded longitudinal observation without real trading.

**Architecture:** Keep the existing FastAPI/PostgreSQL/React app. Add a shared R2 budget and archive collector, a research registry and cohort scorer, a Fomo link intake with explicit review, and read-only API/dashboard views. Reuse finalized RPC and GeckoTerminal adapters. All new network calls write to the same global R2 ledger.

**Tech Stack:** Python 3.12, psycopg/PostgreSQL, FastAPI, React/TypeScript, pytest, Ruff, Docker Compose.

---

### Task 1: Freeze protocol and inspect sources

**Files:** `docs/r2-collection-plan.md`, `docs/r2-universe-candidates.md`, `config/r2-candidates.json`.

- [ ] Record selection thresholds and global call allocation before source calls.
- [ ] Verify official mint and market API contracts; write sources and timestamps.
- [ ] Preserve accepted, rejected and uncertain candidates with distinct reasons and decoder compatibility.
- [ ] Commit the pre-call protocol separately from post-call results.

### Task 2: Shared ledger and bounded source collector

**Files:** `src/rotation/r2_budget.py`, `src/rotation/r2_collect.py`, `tests/test_r2_budget.py`, `tests/test_r2_collect.py`.

- [ ] Add a failing test: two processes/sessions sharing one JSON ledger cannot exceed 2,000 reservations or 1,800 active seconds; a 429 consumes one attempt.
- [ ] Add a failing test: a crash after raw response archiving resumes without duplicate transaction or skipped signature.
- [ ] Implement atomic reservation, session timing, source receipts, raw hashes and checkpointed limited batch collection.
- [ ] Run focused tests, then the full suite; commit collector and tests.

### Task 3: Research universe and cohort calculation

**Files:** `src/rotation/r2_universe.py`, `src/rotation/r2_cohort.py`, `src/rotation/migrations/004_r2_registry.sql`, `src/rotation/store.py`, `tests/test_r2_universe.py`, `tests/test_r2_cohort.py`.

- [ ] Add failing tests for mint identity, dated eligibility, rejected candidates, unknown USD values and reserve-versus-speculative distinction.
- [ ] Add failing tests for actor attribution, technical/unknown labels, gross buy/sell, net per mint, attributed rotation USD and ranking coverage.
- [ ] Implement versioned registry/cohort persistence and deterministic ranking with source signatures.
- [ ] Run focused and full tests; commit registry and cohort.

### Task 4: Fomo proof intake

**Files:** `src/rotation/fomo.py`, `src/rotation/api.py`, `src/rotation/cli.py`, `web/src/main.tsx`, `tests/test_fomo.py`, `docs/r2-fomo-linking.md`.

- [ ] Add failing tests: referral URL and self declaration remain unverified; invalid address and missing proof are rejected; a reviewed proof is distinct from on-chain discovery.
- [ ] Implement local import/export and form fields for profile URL, Solana address, proof type/reference, UTC date, reviewer, status and comment.
- [ ] Document only Fomo routes actually inspected; commit code, tests and guide.

### Task 5: Longitudinal state and interface

**Files:** `src/rotation/r2_sequence.py`, `src/rotation/api.py`, `src/rotation/cli.py`, `web/src/main.tsx`, `web/src/style.css`, `tests/test_r2_sequence.py`.

- [ ] Add failing tests for sale carried across sessions, consumed allocation, unknown opening inventory, future market data and no false A→B rotation from reserve.
- [ ] Implement persisted session state, operation/market chronology and quality reasons; expose budget, universe and cohort API endpoints.
- [ ] Add private dashboard panels and CSV/JSON export; build frontend and inspect it locally.

### Task 6: Bounded live audit and report

**Files:** `data/r2-20260926/`, `docs/r2-wallet-cohort.md`, `docs/r2-report.md`, `README.md`.

- [ ] Run only the preallocated small audit through the global ledger; stop on quota/429 or repeated errors.
- [ ] Publish exact new call counts, selected/rejected mints, signatures, wallet evidence, market coverage, rotations or zero, and null comparators where needed.
- [ ] Verify replay determinism, tests, lint, frontend build and clean Git state; commit reproducible data and factual report.
