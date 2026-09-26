from datetime import datetime, timezone

import pytest

from rotation.real_corpus import METEORA_DLMM
from rotation.solana import RpcError, SolanaDecoder, SolanaRpc

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
WALLET = "Wallet1111111111111111111111111111111111111"
DEX = METEORA_DLMM
SWAP_DATA = "PgQWtn8ozixA8QdrcEevWww8nAMCSwZvX"


def balance(mint, amount, decimals=6, owner=WALLET):
    return {
        "accountIndex": 1,
        "mint": mint,
        "owner": owner,
        "uiTokenAmount": {"amount": str(amount), "decimals": decimals},
    }


def transaction(pre, post, instructions=None, *, err=None, version=0, fee=5000):
    return {
        "slot": 42,
        "blockTime": 1767225600,
        "version": version,
        "meta": {
            "err": err,
            "fee": fee,
            "preTokenBalances": pre,
            "postTokenBalances": post,
            "innerInstructions": [],
        },
        "transaction": {
            "signatures": ["signature"],
            "message": {
                "instructions": instructions or [],
                "accountKeys": [{"pubkey": WALLET, "signer": True}],
            },
        },
    }


def test_balances_are_integer_based_and_unknown_program_stays_unknown():
    raw = transaction(
        [balance("A", 1_000_000), balance("B", 0)], [balance("A", 0), balance("B", 2_000_000)]
    )
    decoded = SolanaDecoder(set()).decode(raw, WALLET, T)
    assert decoded.operation.kind == "unknown"
    assert {(x.mint, x.delta_base, x.decimals) for x in decoded.operation.legs} == {
        ("A", -1_000_000, 6),
        ("B", 2_000_000, 6),
    }
    assert decoded.fee_lamports == 5000 and decoded.operation.quality == "partial"


def test_allowlisted_swap_is_single_operation_even_with_inner_instructions():
    raw = transaction(
        [balance("A", 1_000_000), balance("B", 0)],
        [balance("A", 0), balance("B", 2_000_000)],
        [{"programId": DEX, "data": SWAP_DATA}],
    )
    raw["meta"]["innerInstructions"] = [
        {
            "index": 0,
            "instructions": [
                {"programId": "TokenProgram", "parsed": {"type": "transferChecked"}},
                {"programId": "TokenProgram", "parsed": {"type": "transferChecked"}},
            ],
        }
    ]
    decoded = SolanaDecoder({DEX}).decode(raw, WALLET, T)
    assert decoded.operation.kind == "swap"
    assert len(decoded.operation.legs) == 2


def test_swap_with_technical_wrap_remains_swap():
    raw = transaction(
        [balance("A", 1_000_000), balance("B", 0)],
        [balance("A", 0), balance("B", 2_000_000)],
        [
            {"programId": DEX, "data": SWAP_DATA},
            {"programId": "TokenProgram", "parsed": {"type": "syncNative"}},
        ],
    )
    assert SolanaDecoder({DEX}).decode(raw, WALLET, T).operation.kind == "swap"


def test_failed_unsupported_and_missing_meta_do_not_claim_execution():
    good = transaction([balance("A", 100)], [balance("A", 0)], err={"InstructionError": [0, "x"]})
    failed = SolanaDecoder(set()).decode(good, WALLET, T)
    assert failed.operation.kind == "failed" and failed.fee_lamports == 5000
    unsupported = SolanaDecoder(set()).decode(transaction([], [], version=2), WALLET, T)
    assert unsupported.operation.quality == "unsupported_version"
    missing = SolanaDecoder(set()).decode({"slot": 1, "version": 0, "transaction": {}}, WALLET, T)
    assert missing.operation.quality == "partial"


def test_v1_balance_shape_can_decode_but_incomplete_swap_stays_unknown():
    raw = transaction(
        [balance("A", 100)],
        [balance("A", 0)],
        [
            {"programId": DEX, "data": SWAP_DATA},
            {"programId": "TokenProgram", "parsed": {"type": "transferChecked"}},
        ],
        version=1,
    )
    decoded = SolanaDecoder({DEX}).decode(raw, WALLET, T)
    assert decoded.operation.kind == "unknown"
    assert decoded.operation.quality == "partial"


def test_swap_program_does_not_turn_one_leg_into_transfer():
    raw = transaction(
        [balance("A", 100)],
        [balance("A", 0)],
        [
            {"programId": DEX, "data": SWAP_DATA},
            {"programId": "TokenProgram", "parsed": {"type": "transferChecked"}},
        ],
    )
    decoded = SolanaDecoder({DEX}).decode(raw, WALLET, T)
    assert decoded.operation.kind == "unknown"
    assert decoded.operation.quality == "partial"


def test_non_signing_token_owner_is_not_claimed_directional_trader():
    raw = transaction(
        [balance("A", 100), balance("B", 0)],
        [balance("A", 0), balance("B", 100)],
        [{"programId": DEX, "data": SWAP_DATA}],
    )
    raw["transaction"]["message"]["accountKeys"] = [
        {"pubkey": "Signer", "signer": True},
        {"pubkey": WALLET, "signer": False},
    ]
    decoded = SolanaDecoder({DEX}).decode(raw, WALLET, T)
    assert (decoded.operation.kind, decoded.operation.quality) == ("unknown", "ambiguous_actor")


def test_real_meteora_swap_discriminator_is_required():
    raw = transaction(
        [balance("A", 100), balance("B", 0)],
        [balance("A", 0), balance("B", 100)],
        [{"programId": METEORA_DLMM, "data": "PgQWtn8ozixA8QdrcEevWww8nAMCSwZvX"}],
    )
    decoder = SolanaDecoder({METEORA_DLMM})
    assert decoder.decode(raw, WALLET, T).operation.kind == "swap"
    raw["transaction"]["message"]["instructions"][0]["data"] = "111111111111"
    unknown = decoder.decode(raw, WALLET, T)
    assert (unknown.operation.kind, unknown.operation.quality) == ("unknown", "partial")


def test_two_swap_instructions_with_unproven_route_do_not_claim_one_intention():
    raw = transaction(
        [balance("A", 100), balance("B", 0)],
        [balance("A", 0), balance("B", 100)],
        [{"programId": DEX, "data": SWAP_DATA}, {"programId": DEX, "data": SWAP_DATA}],
    )
    decoded = SolanaDecoder({DEX}).decode(raw, WALLET, T)
    assert (decoded.operation.kind, decoded.operation.quality) == ("unknown", "partial_route")


def test_rpc_rejects_unexpected_errors_and_never_calls_send_transaction():
    class FakeClient:
        def post(self, url, json):
            assert json["method"] == "getTransaction"

            class Response:
                status_code = 200

                def json(self):
                    return {"jsonrpc": "2.0", "error": {"code": -32005, "message": "limited"}}

            return Response()

    rpc = SolanaRpc("https://example.invalid", client=FakeClient(), max_calls=1)
    with pytest.raises(RpcError):
        rpc.transaction("signature")
    assert rpc.calls == 1
    with pytest.raises(RpcError):
        rpc.transaction("signature")


def test_rpc_rejects_broadcast_before_network_call():
    class NoNetwork:
        def post(self, *args, **kwargs):
            raise AssertionError("network must not be reached")

    rpc = SolanaRpc("https://example.invalid", client=NoNetwork())
    with pytest.raises(RpcError, match="allowlisted"):
        rpc.call("sendTransaction", ["signed-payload"])
    assert rpc.calls == 0


def test_rpc_requests_finalized_version_one_transactions():
    class FakeClient:
        def post(self, url, json):
            assert json["params"][1]["maxSupportedTransactionVersion"] == 1

            class Response:
                status_code = 200

                def json(self):
                    return {"result": {"version": 1}}

            return Response()

    assert (
        SolanaRpc("https://example.invalid", client=FakeClient()).transaction("sig")["version"] == 1
    )
