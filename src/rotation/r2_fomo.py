"""Local Fomo public-address evidence inbox; attribution needs explicit review."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PROOF_TYPES = {
    "public_profile_explicit_address",
    "public_transaction_explicit_link",
    "authenticated_profile_and_deposit_screen",
    "authorized_export",
    "other",
}
VERIFIABLE = PROOF_TYPES - {"other"}


def validate_public_address(address: str) -> bool:
    if not isinstance(address, str) or not 32 <= len(address) <= 44:
        return False
    try:
        number = 0
        for char in address:
            number = number * 58 + ALPHABET.index(char)
        length = (number.bit_length() + 7) // 8
        return len(address) - len(address.lstrip("1")) + length == 32
    except ValueError:
        return False


def _safe_reference(value: str) -> bool:
    if not value or any(
        secret in value.lower() for secret in ("cookie=", "seed phrase", "private key")
    ):
        return False
    if value.startswith("https://"):
        parsed = urlparse(value)
        return bool(
            parsed.netloc and not (parsed.netloc == "fomo.family" and parsed.path.startswith("/r/"))
        )
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and len(path.parts) >= 2


class FomoProofStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS proofs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)"
        )
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def add(self, value: dict) -> dict:
        if value.get("network") != "solana" or not validate_public_address(
            value.get("address", "")
        ):
            raise ValueError("valid Solana public address required")
        profile = value.get("profile", "")
        if (
            not isinstance(profile, str)
            or not profile
            or (
                profile.startswith("http")
                and (
                    urlparse(profile).hostname != "fomo.family"
                    or urlparse(profile).path.startswith("/r/")
                )
            )
        ):
            raise ValueError(
                "Fomo profile URL or identifier required; referral URL is not a profile"
            )
        if value.get("proof_type") not in PROOF_TYPES or not _safe_reference(
            value.get("proof_reference", "")
        ):
            raise ValueError("dated public evidence reference required")
        if not value.get("verified_by"):
            raise ValueError("verification author required")
        try:
            date = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise ValueError("UTC verification date required") from exc
        if date.utcoffset() != timezone.utc.utcoffset(date) or date > datetime.now(timezone.utc):
            raise ValueError("verification date must be UTC and not in the future")
        result = {
            key: value.get(key)
            for key in (
                "profile",
                "network",
                "address",
                "proof_type",
                "proof_reference",
                "verified_at",
                "verified_by",
                "comment",
            )
        }
        result.update(
            id=uuid.uuid4().hex,
            status="pending_review",
            attribution="onchain_unattributed",
            imported_at=datetime.now(timezone.utc).isoformat(),
            reviewer=None,
            reviewed_at=None,
        )
        with self.db:
            self.db.execute(
                "INSERT INTO proofs VALUES (?,?)",
                (result["id"], json.dumps(result, sort_keys=True)),
            )
        return result

    def list(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT payload FROM proofs ORDER BY payload")
        ]

    def review(self, proof_id: str, *, reviewer: str, decision: str, review_comment: str) -> dict:
        row = self.db.execute("SELECT payload FROM proofs WHERE id=?", (proof_id,)).fetchone()
        if (
            not row
            or decision not in {"verified", "rejected"}
            or not reviewer
            or not review_comment
        ):
            raise ValueError("explicit reviewer, decision and reason required")
        item = json.loads(row[0])
        if item["status"] != "pending_review":
            raise ValueError("proof has already been reviewed")
        if decision == "verified" and item["proof_type"] not in VERIFIABLE:
            raise ValueError("proof type does not establish explicit profile/address link")
        item.update(
            status=decision,
            attribution="fomo_verified" if decision == "verified" else "onchain_unattributed",
            reviewer=reviewer,
            review_comment=review_comment,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.db:
            self.db.execute(
                "UPDATE proofs SET payload=? WHERE id=?",
                (json.dumps(item, sort_keys=True), proof_id),
            )
        return item
