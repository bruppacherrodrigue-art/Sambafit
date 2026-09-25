"""Local read API and bounded registry editing. No execution endpoints."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine import Leg, Operation, attribute_rotations
from .research import price_operations
from .signals import MarketBar
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
            row["signature"],
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
        return attribute_rotations(price_operations(_operations(rows), bars))

    @app.get("/api/market/{mint}")
    def market(mint: str, dataset: Literal["DEMO", "REAL"] = "DEMO"):
        return store.list_market_bars(mint, datetime.now(timezone.utc), dataset)

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
