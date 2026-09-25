"""PostgreSQL persistence. Schemas isolate tests; modes isolate datasets."""

import json
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class Store:
    def __init__(self, url: str, schema: str = "public"):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
            raise ValueError("invalid schema")
        self.url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        self.schema = schema

    def connect(self):
        return psycopg.connect(
            self.url, row_factory=dict_row, options=f"-c search_path={self.schema}"
        )

    def migrate(self):
        with psycopg.connect(self.url) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema))
            )
        with self.connect() as conn:
            exists = conn.execute("SELECT to_regclass('schema_migrations') AS name").fetchone()[
                "name"
            ]
            if exists is None:
                script = (Path(__file__).parent / "migrations" / "001_init.sql").read_text()
                conn.execute(script)
            applied = conn.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone()
            if applied is None:
                script = (Path(__file__).parent / "migrations" / "002_decoder_time.sql").read_text()
                conn.execute(script)
            applied = conn.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone()
            if applied is None:
                script = (
                    Path(__file__).parent / "migrations" / "003_demo_decoded_time.sql"
                ).read_text()
                conn.execute(script)

    def drop_test_schema(self):
        if not self.schema.startswith("test_"):
            raise ValueError("only test schemas may be dropped")
        with psycopg.connect(self.url) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def import_watchlist(self, entries: list[dict], known_at: str) -> int:
        if not entries:
            raise ValueError("empty watchlist")
        for entry in entries:
            if entry.get("network") != "solana" or not _address(entry.get("mint", "")):
                raise ValueError("watchlist requires Solana mint addresses")
            if not 0 <= int(entry["decimals"]) <= 18:
                raise ValueError("invalid decimals")
            if not entry.get("eligible_from"):
                raise ValueError("eligibility start required")
        hash_value = digest({"known_at": known_at, "entries": entries})
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO watchlist_versions(content_hash,known_at,payload)
                VALUES (%s,%s,%s) ON CONFLICT(content_hash) DO UPDATE SET content_hash=EXCLUDED.content_hash
                RETURNING id""",
                (hash_value, known_at, Jsonb(entries)),
            ).fetchone()
            version = row["id"]
            for entry in entries:
                token = conn.execute(
                    """INSERT INTO tokens(network,mint,symbol,decimals,metadata,active,exclusion_reason)
                    VALUES ('solana',%s,%s,%s,%s,%s,%s) ON CONFLICT(network,mint)
                    DO UPDATE SET symbol=EXCLUDED.symbol, metadata=EXCLUDED.metadata,
                    active=EXCLUDED.active, exclusion_reason=EXCLUDED.exclusion_reason RETURNING id""",
                    (
                        entry["mint"],
                        entry.get("symbol"),
                        entry["decimals"],
                        Jsonb(entry.get("metadata", {})),
                        entry.get("status", "active") == "active",
                        entry.get("exclusion_reason"),
                    ),
                ).fetchone()
                conn.execute(
                    """INSERT INTO watchlist_members(version_id,token_id,eligible_from,eligible_until,status)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT(version_id,token_id) DO NOTHING""",
                    (
                        version,
                        token["id"],
                        entry["eligible_from"],
                        entry.get("eligible_until"),
                        entry.get("status", "active"),
                    ),
                )
        return version

    def list_tokens(self) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT network,mint,symbol,decimals,active,exclusion_reason FROM tokens ORDER BY mint"
            ).fetchall()

    def import_wallets(self, entries: list[dict]):
        for entry in entries:
            if not _address(entry.get("address", "")):
                raise ValueError("wallet requires public Solana address")
            if entry.get("fomo_profile") and not all(
                entry.get(k) for k in ("proof", "verified_at", "confidence")
            ):
                raise ValueError("Fomo attribution needs dated proof and confidence")
        with self.connect() as conn:
            for entry in entries:
                conn.execute(
                    """INSERT INTO wallets(address,category,category_reason)
                    VALUES (%s,%s,%s) ON CONFLICT(address) DO UPDATE SET
                    category=EXCLUDED.category,category_reason=EXCLUDED.category_reason""",
                    (
                        entry["address"],
                        entry.get("category", "unknown"),
                        entry.get("category_reason"),
                    ),
                )
                if entry.get("fomo_profile"):
                    profile = conn.execute(
                        """INSERT INTO profiles(platform,handle,source_url)
                        VALUES ('fomo',%s,%s) ON CONFLICT(platform,handle) DO UPDATE SET
                        source_url=EXCLUDED.source_url RETURNING id""",
                        (entry["fomo_profile"], entry.get("profile_url")),
                    ).fetchone()
                    conn.execute(
                        """INSERT INTO wallet_profile_links(wallet,profile_id,proof,verified_at,confidence)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (
                            entry["address"],
                            profile["id"],
                            entry["proof"],
                            entry["verified_at"],
                            entry["confidence"],
                        ),
                    )

    def list_wallets(self) -> list[dict]:
        with self.connect() as conn:
            return conn.execute("""SELECT w.address,w.category,w.category_reason,p.handle AS fomo_profile,
                l.proof,l.verified_at,l.confidence FROM wallets w
                LEFT JOIN wallet_profile_links l ON l.wallet=w.address
                LEFT JOIN profiles p ON p.id=l.profile_id ORDER BY w.address""").fetchall()

    def add_raw(
        self,
        signature: str,
        wallet: str,
        payload: dict,
        source: str,
        parser_version: str,
        first_seen_at: datetime | None = None,
        dataset: str = "REAL",
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO raw_events(signature,wallet,dataset,slot,block_time,first_seen_at,
                source,parser_version,response_hash,payload) VALUES (%s,%s,%s,%s,
                to_timestamp(%s),COALESCE(%s,now()),%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
                (
                    signature,
                    wallet,
                    dataset,
                    payload.get("slot"),
                    payload.get("blockTime"),
                    first_seen_at,
                    source,
                    parser_version,
                    digest(payload),
                    Jsonb(payload),
                ),
            ).fetchone()
        return row is not None

    def checkpoint(self, wallet: str, cursor: str | None, pages: int, coverage: str):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO checkpoints(wallet,cursor,pages,coverage) VALUES (%s,%s,%s,%s)
                ON CONFLICT(wallet) DO UPDATE SET cursor=EXCLUDED.cursor,pages=EXCLUDED.pages,
                coverage=EXCLUDED.coverage,updated_at=now()""",
                (wallet, cursor, pages, coverage),
            )

    def get_checkpoint(self, wallet: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM checkpoints WHERE wallet=%s", (wallet,)).fetchone()

    def record_decision(
        self,
        pair: str,
        at: datetime,
        state: str,
        quality: str,
        score: int,
        components: dict,
        config_hash: str,
        dataset: str,
        reasons: list[str] | None = None,
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO signal_revisions(pair,decision_at,state,quality,score,
                components,reasons,config_hash,dataset) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING id""",
                (
                    pair,
                    at,
                    state,
                    quality,
                    score,
                    Jsonb(components),
                    Jsonb(reasons or []),
                    config_hash,
                    dataset,
                ),
            ).fetchone()
            if row and state in ("candidate", "confirmed"):
                conn.execute(
                    "INSERT INTO alerts(revision_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (row["id"],),
                )
        return row is not None

    def list_signals(self, dataset: str) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT pair,decision_at,state,quality,score,components,reasons,
                config_hash,dataset FROM signal_revisions WHERE dataset=%s ORDER BY decision_at,id""",
                (dataset,),
            ).fetchall()

    def add_market_bar(
        self,
        mint: str,
        close_at: datetime,
        available_at: datetime,
        price_usd,
        volume_usd,
        liquidity_usd,
        source: str,
        dataset: str,
        source_version: str = "import-1",
    ) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO market_bars(mint,close_at,available_at,price_usd,
                volume_usd,liquidity_usd,source,source_version,dataset) VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
                (
                    mint,
                    close_at,
                    available_at,
                    price_usd,
                    volume_usd,
                    liquidity_usd,
                    source,
                    source_version,
                    dataset,
                ),
            ).fetchone()
        return row is not None

    def list_market_bars(self, mint: str, at: datetime, dataset: str) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT mint,close_at,available_at,price_usd,volume_usd,
                liquidity_usd,source,dataset FROM market_bars WHERE mint=%s AND dataset=%s
                AND close_at<=%s AND available_at<=%s ORDER BY close_at""",
                (mint, dataset, at, at),
            ).fetchall()

    def all_market_bars(self, at: datetime, dataset: str) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT mint,close_at,available_at,price_usd,volume_usd,
                liquidity_usd,source,dataset FROM market_bars WHERE dataset=%s
                AND close_at<=%s AND available_at<=%s ORDER BY available_at,mint""",
                (dataset, at, at),
            ).fetchall()

    def add_operation(
        self,
        signature: str,
        wallet: str,
        operation,
        fee_lamports: int,
        decoder_version: str,
        dataset: str = "REAL",
        decoded_at: datetime | None = None,
    ):
        legs = [
            {
                "mint": leg.mint,
                "delta_base": str(leg.delta_base),
                "decimals": leg.decimals,
                "usd_price": str(leg.usd_price) if leg.usd_price is not None else None,
            }
            for leg in operation.legs
        ]
        with self.connect() as conn:
            raw = conn.execute(
                "SELECT id FROM raw_events WHERE signature=%s AND wallet=%s AND dataset=%s",
                (signature, wallet, dataset),
            ).fetchone()
            if not raw:
                raise ValueError("raw event required before operation")
            conn.execute(
                """INSERT INTO operations(raw_event_id,wallet,economic_at,available_at,
                kind,status,quality,fee_lamports,legs,decoder_version,decoded_at) VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,now())) ON CONFLICT DO NOTHING""",
                (
                    raw["id"],
                    wallet,
                    operation.economic_at,
                    operation.available_at,
                    operation.kind,
                    "finalized" if operation.finalized else "provisional",
                    operation.quality,
                    fee_lamports,
                    Jsonb(legs),
                    decoder_version,
                    decoded_at or (operation.available_at if dataset == "DEMO" else None),
                ),
            )

    def list_operations(self, at: datetime, dataset: str = "REAL") -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT signature,wallet,economic_at,available_at,kind,status,quality,
                fee_lamports,legs,decoder_version,decoded_at FROM (
                  SELECT DISTINCT ON (o.raw_event_id,o.wallet)
                    r.signature,o.wallet,o.economic_at,o.available_at,o.kind,o.status,
                    o.quality,o.fee_lamports,o.legs,o.decoder_version,o.decoded_at,o.id
                  FROM operations o JOIN raw_events r ON r.id=o.raw_event_id
                  WHERE o.available_at<=%s AND o.decoded_at<=%s AND r.dataset=%s
                  ORDER BY o.raw_event_id,o.wallet,o.decoded_at DESC,o.id DESC
                ) latest ORDER BY available_at,id""",
                (at, at, dataset),
            ).fetchall()

    def add_coverage_gap(self, wallet: str, reason: str, start_at: datetime | None = None):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO coverage_gaps(wallet,start_at,reason) VALUES (%s,%s,%s)",
                (wallet, start_at, reason),
            )

    def overview(self, dataset: str) -> dict:
        source_dataset = "REAL" if dataset == "REPLAY" else dataset
        with self.connect() as conn:
            return {
                "dataset": dataset,
                "wallets": conn.execute("SELECT count(*) AS n FROM wallets").fetchone()["n"]
                if source_dataset == "REAL"
                else 0,
                "tokens": conn.execute("SELECT count(*) AS n FROM tokens").fetchone()["n"]
                if source_dataset == "REAL"
                else 0,
                "raw_events": conn.execute(
                    "SELECT count(*) AS n FROM raw_events WHERE dataset=%s", (source_dataset,)
                ).fetchone()["n"],
                "operations": conn.execute(
                    "SELECT count(*) AS n FROM operations o JOIN raw_events r ON r.id=o.raw_event_id WHERE r.dataset=%s",
                    (source_dataset,),
                ).fetchone()["n"],
                "market_bars": conn.execute(
                    "SELECT count(*) AS n FROM market_bars WHERE dataset=%s", (source_dataset,)
                ).fetchone()["n"],
                "signals": conn.execute(
                    "SELECT count(*) AS n FROM signal_revisions WHERE dataset=%s", (dataset,)
                ).fetchone()["n"],
                "open_gaps": conn.execute(
                    "SELECT count(*) AS n FROM coverage_gaps WHERE resolved_at IS NULL"
                ).fetchone()["n"],
            }

    def save_experiment(
        self, run_id: str, config_hash: str, dataset: str, status: str, result: dict
    ):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO experiments(id,config_hash,dataset,started_at,ended_at,status,result)
                VALUES (%s,%s,%s,now(),now(),%s,%s)""",
                (run_id, config_hash, dataset, status, Jsonb(result)),
            )

    def get_experiment(self, run_id: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute(
                """SELECT id,config_hash,dataset,started_at,ended_at,status,result
                FROM experiments WHERE id=%s""",
                (run_id,),
            ).fetchone()

    def list_experiments(self, dataset: str) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT id,config_hash,dataset,started_at,ended_at,status,result
                FROM experiments WHERE dataset=%s ORDER BY started_at DESC LIMIT 100""",
                (dataset,),
            ).fetchall()

    def save_paper(self, run_id: str, initial_cash, book, orders: list[dict]):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO paper_portfolios(id,experiment_id,initial_cash,cash,holdings,fees)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    run_id,
                    run_id,
                    initial_cash,
                    book.cash,
                    Jsonb({mint: str(qty) for mint, qty in book.positions.items()}),
                    book.fees,
                ),
            )
            for order in orders:
                conn.execute(
                    """INSERT INTO paper_orders(id,portfolio_id,mint,side,quantity,status,
                    intended_at,filled_at,price,fee) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        f"{run_id}-{order['id']}",
                        run_id,
                        order.get("mint", "unknown"),
                        order["side"],
                        order.get("quantity", "0"),
                        order["status"],
                        order.get("intended_at") or order.get("at") or datetime.now().astimezone(),
                        order.get("at") if order["status"] == "filled" else None,
                        order.get("price"),
                        order.get("fee"),
                    ),
                )

    def get_evidence(self, signature: str, dataset: str, wallet: str | None = None) -> dict | None:
        with self.connect() as conn:
            raw = conn.execute(
                """SELECT id,signature,wallet,slot,block_time,first_seen_at,
                ingested_at,source,parser_version,response_hash,payload,dataset FROM raw_events
                WHERE signature=%s AND dataset=%s AND (%s::text IS NULL OR wallet=%s)
                ORDER BY id LIMIT 1""",
                (signature, dataset, wallet, wallet),
            ).fetchone()
            if not raw:
                return None
            operation = conn.execute(
                """SELECT economic_at,available_at,kind,status,quality,
                fee_lamports,legs,decoder_version,decoded_at FROM operations WHERE raw_event_id=%s
                ORDER BY decoded_at DESC,id DESC LIMIT 1""",
                (raw["id"],),
            ).fetchone()
            return {"raw": raw, "operation": operation}

    def coverage(self) -> dict:
        with self.connect() as conn:
            return {
                "checkpoints": conn.execute(
                    "SELECT * FROM checkpoints ORDER BY updated_at DESC LIMIT 100"
                ).fetchall(),
                "gaps": conn.execute(
                    "SELECT * FROM coverage_gaps WHERE resolved_at IS NULL ORDER BY detected_at DESC LIMIT 100"
                ).fetchall(),
            }


def _address(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", value))
