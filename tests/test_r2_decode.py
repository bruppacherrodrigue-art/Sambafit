from datetime import datetime, timezone
from decimal import Decimal

from rotation.market import TradeRef
from rotation.r2_decode import RAYDIUM_AMM_V4, R2Decoder

T = datetime(2026, 9, 26, tzinfo=timezone.utc)
OWNER = "Owner1111111111111111111111111111111111111"


def balance(mint, amount):
    return {"owner": OWNER, "mint": mint, "uiTokenAmount": {"amount": str(amount), "decimals": 6}}


def tx(program, data="A", *, inner=None, failed=False, sign=True):
    return {
        "slot": 1,
        "blockTime": 1790413503,
        "version": 0,
        "meta": {
            "err": {"InstructionError": [0, "Custom"]} if failed else None,
            "fee": 5000,
            "preTokenBalances": [balance("A", 100), balance("B", 0)],
            "postTokenBalances": [balance("A", 0), balance("B", 200)],
            "innerInstructions": [{"index": 0, "instructions": inner or []}],
        },
        "transaction": {
            "signatures": ["sig"],
            "message": {
                "accountKeys": [{"pubkey": OWNER, "signer": sign}],
                "instructions": [{"programId": program, "data": data}],
            },
        },
    }


def test_raydium_swap_tag_is_one_operation_and_preserves_fee():
    decoded = R2Decoder().decode(tx(RAYDIUM_AMM_V4, "A"), OWNER, T)
    assert (decoded.operation.kind, decoded.operation.quality) == ("swap", "complete")
    assert decoded.fee_lamports == 5000
    assert {(leg.mint, leg.delta_base) for leg in decoded.operation.legs} == {
        ("A", -100),
        ("B", 200),
    }


def test_unknown_program_and_multiple_swaps_are_not_transfer_or_route_claims():
    assert R2Decoder().decode(tx("unknown", "A"), OWNER, T).operation.kind == "unknown"
    routed = tx(RAYDIUM_AMM_V4, "A", inner=[{"programId": RAYDIUM_AMM_V4, "data": "A"}])
    got = R2Decoder().decode(routed, OWNER, T)
    assert (got.operation.kind, got.operation.quality) == ("unknown", "partial_route")


def test_unproven_owner_and_failed_tx_never_claim_swap():
    assert (
        R2Decoder().decode(tx(RAYDIUM_AMM_V4, "A", sign=False), OWNER, T).operation.kind
        == "unknown"
    )
    assert (
        R2Decoder().decode(tx(RAYDIUM_AMM_V4, "A", failed=True), OWNER, T).operation.kind
        == "failed"
    )


def test_provider_pair_must_match_owner_deltas_before_direct_attribution():
    reference = TradeRef(
        "sig",
        1,
        T,
        OWNER,
        "buy",
        "A",
        "C",
        Decimal("0.0001"),
        Decimal("0.0002"),
        Decimal("1"),
        "pool",
    )
    decoded = R2Decoder().decode(tx(RAYDIUM_AMM_V4, "A"), OWNER, T, reference)
    assert (decoded.operation.kind, decoded.operation.quality) == ("unknown", "partial_route")
