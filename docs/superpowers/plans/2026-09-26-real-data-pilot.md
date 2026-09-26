# Real Data Pilot Implementation Plan

> For agentic workers: execute locally in the isolated `feat/real-data-pilot` worktree. Follow TDD and verify each claim.

## Files and boundaries

- `src/rotation/solana.py`: read-only RPC, roles and conservative decoding.
- `src/rotation/market.py`: GeckoTerminal documented HTTP adapter and candle/pool parsing.
- `src/rotation/pilot.py`: shared request/time/transaction budget, deterministic discovery, manifest and checkpoints.
- `src/rotation/store.py` plus migration: provenance, technical cohort and market observations.
- `src/rotation/replay.py`, `research.py`, `comparison.py`: strict replay and four comparable policies.
- `src/rotation/api.py`, `web/src/main.tsx`: real operation list, evidence and chronology.
- `tests/`: failing tests first for each behavior, then real fixture regressions.
- `docs/real-pilot-report.md`: measured calls, counts, classifications and limits.

## Sequence

1. Inspect baseline, commit gap matrix and preregistered protocol. Verify Git and test baseline.
2. Write failing budget and market-adapter tests. Implement bounded public API calls, observed times and raw provenance. Verify contracts with tiny live requests.
3. Use one small pool/trade sample to obtain raw RPC examples. Write failing decoder regressions from the raw examples; implement role separation and safe net-balance classification. Keep unsupported cases explicit.
4. Expand only within the protocol limits. Persist manifest, candidate provenance, exact coverage and manually review up to 10 swaps. Commit corpus and report measured results.
5. Write failing tests for replay from corpus, as-of watchlist/cohort filtering and no duplicate decisions. Implement minimal point-in-time path.
6. Write failing tests for four variants on common bars and capital. Implement comparator; mark real results non-evaluable if history or liquidity is absent.
7. Add API and dashboard real-operation evidence view with a failing API test and build check. Keep controls loopback.
8. Run full tests, linter, build, deterministic replay twice and a bounded pilot reproduction. Review manifests and Git diff; commit coherent changes. No remote or real execution.
