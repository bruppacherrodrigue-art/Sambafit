import pytest

from rotation.r2_fomo import FomoProofStore, validate_public_address

ADDRESS = "So11111111111111111111111111111111111111112"


def record(**changes):
    value = {
        "profile": "https://fomo.family/example-profile",
        "network": "solana",
        "address": ADDRESS,
        "proof_type": "public_profile_explicit_address",
        "proof_reference": "evidence/screen.png",
        "verified_at": "2026-09-26T08:00:00Z",
        "verified_by": "operator",
        "status": "proposed",
        "comment": "public wallet visible",
    }
    value.update(changes)
    return value


def test_valid_pubkey_and_referral_cannot_be_proof(tmp_path):
    assert validate_public_address(ADDRESS)
    assert not validate_public_address("bad-wallet")
    with FomoProofStore(tmp_path / "proofs.sqlite") as store:
        with pytest.raises(ValueError):
            store.add(record(profile="https://fomo.family/r/nobrainflip"))
        with pytest.raises(ValueError):
            store.add(record(proof_reference="https://fomo.family/r/nobrainflip"))
        with pytest.raises(ValueError):
            store.add(record(address="bad-wallet"))


def test_import_is_pending_until_separate_review(tmp_path):
    with FomoProofStore(tmp_path / "proofs.sqlite") as store:
        proof = store.add(record())
        assert proof["status"] == "pending_review"
        assert store.list()[0]["attribution"] == "onchain_unattributed"
        reviewed = store.review(
            proof["id"],
            reviewer="human",
            decision="verified",
            review_comment="inspected public screenshot showing both fields",
        )
        assert reviewed["status"] == "verified"
        assert store.list()[0]["attribution"] == "fomo_verified"


def test_unsupported_proof_cannot_be_promoted(tmp_path):
    with FomoProofStore(tmp_path / "proofs.sqlite") as store:
        proof = store.add(record(proof_type="other"))
        with pytest.raises(ValueError):
            store.review(
                proof["id"], reviewer="human", decision="verified", review_comment="unclear"
            )
