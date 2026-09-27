"""Local read API and bounded registry editing. No execution endpoints."""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine import Leg, Operation, aggregate_convergence, attribute_rotations
from .market import parse_candles
from .r2_collect import SIGNATURE
from .r2_fomo import FomoProofStore
from .research import price_operations
from .signals import MarketBar, decide, market_features
from .store import Store

Dataset = Literal["DEMO", "REAL", "REPLAY", "PAPER LIVE"]


class WatchlistImport(BaseModel):
    known_at: datetime
    entries: list[dict] = Field(min_length=1, max_length=100)


class WalletImport(BaseModel):
    entries: list[dict] = Field(min_length=1, max_length=100)


def _operations(rows: list[dict]) -> list[Operation]:
    return [
        Operation(
            row.get("canonical_id", row["signature"]),
            row["wallet"],
            row["signature"],
            row["economic_at"],
            row["available_at"],
            row["kind"],
            tuple(
                Leg(
                    item["mint"],
                    int(item["delta_base"]),
                    int(item["decimals"]),
                    Decimal(item["usd_price"]) if item["usd_price"] is not None else None,
                )
                for item in row["legs"]
            ),
            row["status"] == "finalized",
            row["quality"],
        )
        for row in rows
    ]


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store(
        os.getenv("DATABASE_URL", "postgresql://rotation:rotation@127.0.0.1:55432/rotation"),
        os.getenv("ROTATION_SCHEMA", "public"),
    )
    app = FastAPI(title="Rotation Engine — local research", version="0.1.0")
    r2_root = Path(
        os.getenv(
            "ROTATION_R2_DIR", str(Path(__file__).resolve().parents[2] / "data" / "r2-20260926")
        )
    )
    r3_root = Path(
        os.getenv(
            "ROTATION_R3_DIR", str(Path(__file__).resolve().parents[2] / "data" / "r3-20260927")
        )
    )
    r31_root = Path(
        os.getenv(
            "ROTATION_R31_DIR", str(Path(__file__).resolve().parents[2] / "data" / "r3-1-20260927")
        )
    )

    def r3_file(name: str):
        path = r3_root / name
        if not path.exists():
            raise HTTPException(404, "R3 corpus unavailable")
        return json.loads(path.read_text())

    def r31_file(name: str):
        path = r31_root / name
        if not path.exists():
            raise HTTPException(404, "R3.1 offline replay unavailable")
        value = json.loads(path.read_text())
        if (
            value.get("dataset") != "REAL"
            or value.get("synthetic") is True
            or value.get("mode") != "REPLAY"
        ):
            raise HTTPException(409, "R3.1 REAL replay endpoint rejects DEMO or live artifacts")
        return value

    @app.get("/api/r3-1/replay")
    def r31_replay():
        return r31_file("replay.json")

    @app.get("/api/r3-1/prospective")
    def r31_prospective():
        return r31_file("prospective.json")

    @app.get("/api/r3-1/strategy")
    def r31_strategy():
        path = Path(__file__).resolve().parents[2] / "config" / "strategy-r3-1.json"
        return json.loads(path.read_text())

    @app.get("/api/r3/universe")
    def r3_universe():
        path = r3_root.parent.parent / "config" / "r3-universe.json"
        if not path.exists():
            raise HTTPException(404, "R3 classification unavailable")
        return json.loads(path.read_text())

    @app.get("/api/r3/cohort")
    def r3_cohort():
        return r3_file("cohort.json")

    @app.get("/api/r3/replay")
    def r3_replay():
        return r3_file("replay.json")

    @app.get("/api/r3/prospective")
    def r3_prospective():
        return r3_file("prospective.json")

    @app.get("/api/r3/budget")
    def r3_budget():
        value = r3_file("budget.json")
        return {
            "limits": value["limits"],
            "calls_used": value["calls_used"],
            "active_seconds": value["active_seconds"],
            "phase_limits": value["phase_limits"],
            "active_session": value["active_session"],
            "errors": [row for row in value["attempts"] if row["status"] != "http_200"],
        }

    @app.get("/api/r3/market/{mint}")
    def r3_market(mint: str):
        universe = r3_universe()
        if mint not in {row["mint"] for row in universe["records"] if row["role"] == "target"}:
            raise HTTPException(404, "R3 target mint unavailable")
        from .r3_pipeline import load_r2_market_bars

        bars = load_r2_market_bars(r2_root)
        followed_path = r3_root / "market-bars.json"
        followed = json.loads(followed_path.read_text())["bars"] if followed_path.exists() else []
        historical = [
            {
                "mint": bar.mint,
                "close_at": bar.close_at.isoformat(),
                "available_at": bar.available_at.isoformat(),
                "price_usd": str(bar.close_usd),
                "volume_usd": str(bar.volume_usd) if bar.volume_usd is not None else None,
                "liquidity_usd": None,
                "interval_seconds": bar.interval_seconds,
                "source": "R2 archived GeckoTerminal minute OHLCV",
                "dataset": "REAL",
            }
            for bar in bars
            if bar.mint == mint
        ]
        return sorted(
            historical
            + [
                {**row, "dataset": "REAL", "source": "R3 received GeckoTerminal minute OHLCV"}
                for row in followed
                if row["mint"] == mint
            ],
            key=lambda row: (row["close_at"], row["available_at"]),
        )

    @app.get("/api/r3/operations/{signature}")
    def r3_operation(signature: str):
        if not SIGNATURE.fullmatch(signature):
            raise HTTPException(404, "real Solana signature required")
        selected = r3_file("preselection.json")["references"]
        row = next((item for item in selected if item["signature"] == signature), None)
        follow_path = r3_root / "follow-checkpoint.json"
        follow = (
            json.loads(follow_path.read_text()) if follow_path.exists() else {"transactions": {}}
        )
        followed = follow["transactions"].get(signature)
        if row is None and followed is None:
            raise HTTPException(404, "operation outside R3 corpus")
        raw_path = r3_root / "raw" / f"{signature}.json"
        if not raw_path.exists():
            raw_path = r3_root / "follow-raw" / f"{signature}.json"
        if not raw_path.exists():
            raise HTTPException(404, "raw operation unavailable")
        allocations = [
            item
            for item in r3_file("cohort.json")["sequences"]["allocations"]
            if signature in (item["source_signature"], item["destination_signature"])
        ]
        replay_rows = r3_file("replay.json")
        related_pairs = {
            f"{item['source_mint']}:{item['destination_mint']}" for item in allocations
        }
        decisions = [item for item in replay_rows["decisions"] if item["pair"] in related_pairs]
        return {
            "dataset": "REAL",
            "mode": "REPLAY" if row else "PAPER LIVE",
            "operation": row or {"signature": signature, **followed},
            "raw": json.loads(raw_path.read_text()),
            "allocations": allocations,
            "decisions": decisions,
            "provenance": (row or followed).get("raw_source", "r3_follow_rpc"),
            "limitations": [
                "sampled coverage; opening positions unknown",
                "provider USD is a trade-time proxy, not an executable quote",
            ],
        }

    def r2_file(name: str):
        path = r2_root / name
        if not path.exists():
            raise HTTPException(404, "R2 corpus unavailable")
        return json.loads(path.read_text())

    @app.get("/api/r2/universe")
    def r2_universe():
        path = r2_root.parent.parent / "config" / "r2-candidates.json"
        if not path.exists():
            raise HTTPException(404, "R2 universe unavailable")
        return json.loads(path.read_text())

    @app.get("/api/r2/cohort")
    def r2_cohort():
        value = r2_file("cohort.json")
        return {
            "scope": value["scope"],
            "summary": value["summary"],
            "cohort_known_at": value["cohort_known_at"],
            "wallets": value["wallets"],
            "per_coin_ranking": value.get("per_coin_ranking", {}),
            "ranking_note": value.get("ranking_note"),
        }

    @app.get("/api/r2/market/{mint}")
    def r2_market(mint: str):
        universe = r2_universe()
        record = next(
            (
                r
                for r in universe["records"]
                if r["mint"] == mint and r["status"] == "research_candidate"
            ),
            None,
        )
        if record is None:
            raise HTTPException(404, "candidate mint unavailable")
        attempt = record["source_attempts"][1]
        source = r2_file(f"source/attempt-{attempt:04}.json")
        candles = parse_candles(
            json.loads(source["body"], parse_float=Decimal),
            record["primary_pool"],
            mint,
            datetime.fromisoformat(source["received_at"]),
            seconds=86400,
        )
        return [
            {
                "mint": mint,
                "close_at": c.close_at,
                "available_at": c.received_at,
                "price_usd": c.close_usd,
                "volume_usd": c.volume_usd,
                "liquidity_usd": None,
                "source": "GeckoTerminal closed daily OHLCV; archival receipt",
                "dataset": "REAL",
            }
            for c in candles
        ]

    @app.get("/api/r2/sequences")
    def r2_sequences():
        return r2_file("sequences.json")

    @app.get("/api/r2/budget")
    def r2_budget():
        value = r2_file("budget.json")
        return {
            "limits": value["limits"],
            "calls_used": value["calls_used"],
            "active_seconds": value["active_seconds"],
            "active_session": value["active_session"],
            "errors": [a for a in value["attempts"] if a["status"] not in {"http_200"}],
        }

    @app.get("/api/r2/follow")
    def r2_follow():
        return r2_file("follow-checkpoint.json")

    @app.get("/api/r2/evidence/{signature}")
    def r2_evidence(signature: str):
        rows = r2_file("tx-selection.json")["records"]
        row = next(
            (r for r in rows if r["signature"] == signature and r["status"] == "fetched"), None
        )
        if row is None:
            raise HTTPException(404, "R2 signature unavailable")
        return {
            "dataset": "REAL",
            "selection": row,
            "raw": r2_file(f"raw/{signature}.json"),
            "events": [e for e in r2_file("cohort.json")["events"] if e["signature"] == signature],
            "allocations": [
                a
                for a in r2_file("sequences.json")["allocations"]
                if signature in (a["source_signature"], a["destination_signature"])
            ],
        }

    @app.get("/api/r2/fomo-proofs")
    def r2_fomo_proofs():
        with FomoProofStore(r2_root / "fomo-proofs.sqlite") as proofs:
            return proofs.list()

    @app.post("/api/r2/fomo-proofs")
    def r2_add_fomo_proof(record: dict):
        try:
            with FomoProofStore(r2_root / "fomo-proofs.sqlite") as proofs:
                return proofs.add(record)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/health")
    def health():
        return {
            "service": "rotation-engine",
            "execution_enabled": False,
            "kill_switch": os.getenv("ROTATION_KILL_SWITCH") == "1",
        }

    @app.get("/api/overview")
    def overview(dataset: Dataset = "DEMO"):
        return store.overview(dataset)

    @app.get("/api/tokens")
    def tokens(dataset: Dataset = "REAL"):
        return store.list_tokens() if dataset != "DEMO" else []

    @app.get("/api/wallets")
    def wallets(dataset: Dataset = "REAL"):
        return store.list_wallets() if dataset != "DEMO" else []

    @app.get("/api/signals")
    def signals(dataset: Dataset = "DEMO"):
        return store.list_signals(dataset)

    @app.get("/api/experiments")
    def experiments(dataset: Dataset = "DEMO"):
        return store.list_experiments(dataset)

    @app.get("/api/coverage")
    def coverage(dataset: Literal["DEMO", "REAL"] = "DEMO"):
        if dataset == "DEMO":
            return {"checkpoints": [], "gaps": [], "note": "synthetic fixture; no collection"}
        return store.coverage()

    @app.get("/api/evidence/{signature}")
    def evidence(
        signature: str, dataset: Literal["DEMO", "REAL"] = "DEMO", wallet: str | None = None
    ):
        value = store.get_evidence(signature, dataset, wallet)
        if value is None:
            raise HTTPException(404, "evidence not found in dataset")
        return value

    @app.get("/api/operations")
    def operations(dataset: Literal["DEMO", "REAL"] = "DEMO"):
        return store.list_operations(datetime.now(timezone.utc), dataset)

    @app.get("/api/operation-context/{signature}")
    def operation_context(
        signature: str, dataset: Literal["DEMO", "REAL"] = "DEMO", wallet: str | None = None
    ):
        rows = [
            row
            for row in store.list_operations(datetime.now(timezone.utc), dataset)
            if row["signature"] == signature and (wallet is None or row["wallet"] == wallet)
        ]
        if not rows:
            raise HTTPException(404, "operation not found in dataset")
        row = rows[0]
        at = row["available_at"]
        market_rows = store.all_market_bars(at, dataset)
        bars = [
            MarketBar(
                item["mint"],
                item["close_at"],
                item["available_at"],
                item["price_usd"],
                item["volume_usd"] or Decimal(0),
                item["liquidity_usd"],
            )
            for item in market_rows
        ]
        operation = price_operations(_operations([row]), bars)[0]
        rotations = attribute_rotations(
            [operation],
            stable_mints={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
            reserve_mints={"So11111111111111111111111111111111111111112"},
        )
        decision = decide(rotations, bars, at)
        return {
            "dataset": dataset,
            "signature": signature,
            "wallet": row["wallet"],
            "economic_at": row["economic_at"],
            "available_at": at,
            "decoded_at": row["decoded_at"],
            "rotations": rotations,
            "market_features": {
                leg.mint: market_features(bars, leg.mint, at) for leg in operation.legs
            },
            "decision": decision,
            "note": "backfill availability is this run's receipt/decode, not historic bot latency",
        }

    @app.get("/api/rotations")
    def rotations(dataset: Literal["DEMO", "REAL"] = "DEMO"):
        at = datetime.now(timezone.utc)
        rows = store.list_operations(at, dataset)
        bars = [
            MarketBar(
                row["mint"],
                row["close_at"],
                row["available_at"],
                row["price_usd"],
                row["volume_usd"] or Decimal(0),
                row["liquidity_usd"],
            )
            for row in store.all_market_bars(at, dataset)
        ]
        result = attribute_rotations(
            price_operations(_operations(rows), bars),
            stable_mints={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
            reserve_mints={"So11111111111111111111111111111111111111112"},
        )
        if dataset == "REAL":
            eligible = {token["mint"] for token in store.list_tokens() if token["active"]}
            result = [
                r
                for r in result
                if r.source in eligible and (r.destination is None or r.destination in eligible)
            ]
        return result

    @app.get("/api/market/{mint}")
    def market(mint: str, dataset: Literal["DEMO", "REAL"] = "DEMO"):
        return store.list_market_bars(mint, datetime.now(timezone.utc), dataset)

    @app.get("/api/aggregate-flows")
    def aggregate_flows(dataset: Literal["DEMO", "REAL"] = "DEMO"):
        at = datetime.now(timezone.utc)
        rows = store.list_operations(at, dataset)
        bars = [
            MarketBar(
                row["mint"],
                row["close_at"],
                row["available_at"],
                row["price_usd"],
                row["volume_usd"] or Decimal(0),
                row["liquidity_usd"],
            )
            for row in store.all_market_bars(at, dataset)
        ]
        flows = aggregate_convergence(price_operations(_operations(rows), bars), at)
        if dataset == "REAL":
            eligible = {token["mint"] for token in store.list_tokens() if token["active"]}
            flows = [
                flow for flow in flows if flow.source in eligible and flow.destination in eligible
            ]
        return flows

    @app.post("/api/watchlists")
    def import_watchlist(request: WatchlistImport):
        try:
            version = store.import_watchlist(request.entries, request.known_at.isoformat())
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"version_id": version}

    @app.post("/api/wallets")
    def import_wallets(request: WalletImport):
        try:
            store.import_wallets(request.entries)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"imported": len(request.entries)}

    return app


app = create_app()
