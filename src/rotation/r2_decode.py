"""Conservative R2 decoder for owner balance changes on supported DEX instructions.

One signed owner, one documented swap instruction and exactly two opposite token
balance changes are required. Complex routes stay unknown; they are not silently
reclassified as transfers or one economic swap.
"""

from dataclasses import replace
from decimal import Decimal

from .market import TradeRef
from .solana import METEORA_DLMM, SolanaDecoder, _base58_prefix

R2_PARSER_VERSION = "r2-raydium-amm-v4-owner-balances-1"
RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
ORCA_WHIRLPOOLS = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
JUPITER_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
KNOWN_DEX = {METEORA_DLMM, RAYDIUM_AMM_V4, ORCA_WHIRLPOOLS, RAYDIUM_CPMM, JUPITER_V6, PUMP_SWAP}
# Raydium AMM v4 source instruction.rs: swapBaseIn=9, swapBaseOut=11,
# swapBaseInV2=16, swapBaseOutV2=17. The tag is the first decoded byte.
RAYDIUM_SWAP_TAGS = {9, 11, 16, 17}


class R2Decoder:
    def __init__(self):
        self.meteora = SolanaDecoder({METEORA_DLMM})

    def decode(self, tx: dict, wallet: str, available_at, reference: TradeRef | None = None):
        initial = self.meteora.decode(tx, wallet, available_at)
        op = initial.operation
        if op.kind == "failed" or op.quality == "unsupported_version":
            return replace(initial, parser_version=R2_PARSER_VERSION)
        message = (tx.get("transaction") or {}).get("message") or {}
        meta = tx.get("meta") or {}
        instructions = list(message.get("instructions") or [])
        for group in meta.get("innerInstructions") or []:
            instructions.extend(group.get("instructions") or [])
        dex = [item for item in instructions if item.get("programId") in KNOWN_DEX]
        raydium = [item for item in dex if item.get("programId") == RAYDIUM_AMM_V4]
        if raydium:
            tags = [
                _base58_prefix(item.get("data", ""))
                for item in raydium
                if isinstance(item.get("data"), str)
            ]
            swap_tags = [tag[0] for tag in tags if tag]
            signed = any(
                isinstance(key, dict) and key.get("pubkey") == wallet and key.get("signer") is True
                for key in message.get("accountKeys") or []
            )
            neg = [leg for leg in op.legs if leg.delta_base < 0]
            pos = [leg for leg in op.legs if leg.delta_base > 0]
            if len(dex) > 1:
                quality, kind = "partial_route", "unknown"
            elif swap_tags and swap_tags[0] in RAYDIUM_SWAP_TAGS and len(neg) == len(pos) == 1:
                quality, kind = ("complete", "swap") if signed else ("ambiguous_actor", "unknown")
            else:
                quality, kind = "partial", "unknown"
            if kind == "swap" and reference and not self._reference_matches(op, reference):
                quality, kind = "partial_route", "unknown"
            return replace(
                initial,
                operation=replace(op, quality=quality, kind=kind),
                parser_version=R2_PARSER_VERSION,
            )
        if dex and (len(dex) > 1 or op.kind != "swap"):
            quality = "partial_route" if len(dex) > 1 else "unsupported_program"
            return replace(
                initial,
                operation=replace(op, kind="unknown", quality=quality),
                parser_version=R2_PARSER_VERSION,
            )
        if op.kind == "swap" and reference and not self._reference_matches(op, reference):
            return replace(
                initial,
                operation=replace(op, kind="unknown", quality="partial_route"),
                parser_version=R2_PARSER_VERSION,
            )
        return replace(initial, parser_version=R2_PARSER_VERSION)

    @staticmethod
    def _reference_matches(op, reference: TradeRef) -> bool:
        if reference.from_amount <= 0 or reference.to_amount <= 0:
            return False
        amounts = {
            leg.mint: Decimal(abs(leg.delta_base)) / (Decimal(10) ** leg.decimals)
            for leg in op.legs
        }
        if set(amounts) != {reference.from_mint, reference.to_mint}:
            return False
        for mint, expected in (
            (reference.from_mint, reference.from_amount),
            (reference.to_mint, reference.to_amount),
        ):
            if abs(amounts[mint] - expected) / expected > Decimal("0.01"):
                return False
        return True
