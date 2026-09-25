from datetime import datetime, timezone

import pytest

from rotation.solana import RpcError, SolanaDecoder, SolanaRpc

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
WALLET = "Wallet1111111111111111111111111111111111111"


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
            "message": {"instructions": instructions or [], "accountKeys": [{"pubkey": WALLET}]},
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
        [{"programId": "KnownDex", "parsed": {"type": "route"}}],
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
    decoded = SolanaDecoder({"KnownDex"}).decode(raw, WALLET, T)
    assert decoded.operation.kind == "swap"
    assert len(decoded.operation.legs) == 2


def test_swap_with_technical_wrap_remains_swap():
    raw = transaction(
        [balance("A", 1_000_000), balance("B", 0)],
        [balance("A", 0), balance("B", 2_000_000)],
        [
            {"programId": "KnownDex", "parsed": {"type": "route"}},
            {"programId": "TokenProgram", "parsed": {"type": "syncNative"}},
        ],
    )
    assert SolanaDecoder({"KnownDex"}).decode(raw, WALLET, T).operation.kind == "swap"


def test_failed_unsupported_and_missing_meta_do_not_claim_execution():
    good = transaction([balance("A", 100)], [balance("A", 0)], err={"InstructionError": [0, "x"]})
    failed = SolanaDecoder(set()).decode(good, WALLET, T)
    assert failed.operation.kind == "failed" and failed.fee_lamports == 5000
    unsupported = SolanaDecoder(set()).decode(transaction([], [], version=1), WALLET, T)
    assert unsupported.operation.quality == "unsupported_version"
    missing = SolanaDecoder(set()).decode({"slot": 1, "version": 0, "transaction": {}}, WALLET, T)
    assert missing.operation.quality == "partial"


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
