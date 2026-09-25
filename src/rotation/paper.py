"""Deterministic paper ledger. No network or execution capability."""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from .replay import DecisionRecord
from .signals import MarketBar


@dataclass
class PaperBook:
    cash: Decimal
    positions: dict[str, Decimal] = field(default_factory=dict)
    orders: dict[str, str] = field(default_factory=dict)
    fees: Decimal = Decimal(0)

    def sell(
        self,
        mint: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        order_id: str,
        executable: bool = True,
    ) -> str:
        if order_id in self.orders:
            return self.orders[order_id]
        if not executable:
            self.orders[order_id] = "unfilled"
            return "unfilled"
        if (
            quantity <= 0
            or price <= 0
            or fee < 0
            or self.positions.get(mint, Decimal(0)) < quantity
        ):
            raise ValueError("invalid paper sale")
        self.positions[mint] -= quantity
        if self.positions[mint] == 0:
            del self.positions[mint]
        self.cash += quantity * price - fee
        self.fees += fee
        self.orders[order_id] = "filled"
        return "filled"

    def buy(
        self,
        mint: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        order_id: str,
        executable: bool = True,
    ) -> str:
        if order_id in self.orders:
            return self.orders[order_id]
        if not executable:
            self.orders[order_id] = "unfilled"
            return "unfilled"
        cost = quantity * price + fee
        if quantity <= 0 or price <= 0 or fee < 0 or self.cash < cost:
            raise ValueError("invalid paper buy or insufficient cash")
        self.cash -= cost
        self.positions[mint] = self.positions.get(mint, Decimal(0)) + quantity
        self.fees += fee
        self.orders[order_id] = "filled"
        return "filled"


@dataclass(frozen=True)
class PaperSimulation:
    book: PaperBook
    orders: tuple[dict, ...]


def simulate_paper(
    decisions: tuple[DecisionRecord, ...],
    bars: list[MarketBar],
    initial_cash: Decimal,
    *,
    allocation_fraction: Decimal = Decimal("0.25"),
    fee_rate: Decimal = Decimal("0.005"),
    impact_rate: Decimal = Decimal("0.005"),
    network_fee: Decimal = Decimal("0.01"),
    min_liquidity_multiple: Decimal = Decimal("10"),
    max_positions: int = 3,
    reserve_fraction: Decimal = Decimal("0.20"),
    max_loss_fraction: Decimal = Decimal("0.20"),
    max_mark_age: timedelta = timedelta(minutes=30),
) -> PaperSimulation:
    """Reserve-funded policy; process all fills by quote availability time."""
    if (
        initial_cash < 0
        or not 0 < allocation_fraction <= 1
        or fee_rate < 0
        or impact_rate < 0
        or network_fee < 0
        or max_positions < 1
        or not 0 <= reserve_fraction < 1
        or not 0 < max_loss_fraction < 1
        or max_mark_age <= timedelta(0)
    ):
        raise ValueError("invalid paper policy")
    book = PaperBook(initial_cash)
    orders: list[dict] = []
    ordered = sorted(bars, key=lambda b: (b.available_at, b.close_at))
    planned: list[tuple] = []
    for index, record in enumerate(decisions):
        if ":" not in record.pair or record.decision.state not in ("confirmed", "invalidated"):
            continue
        mint = record.pair.split(":", 1)[1]
        next_bar = next(
            (
                b
                for b in ordered
                if b.mint == mint and b.available_at > record.at and b.close_at <= b.available_at
            ),
            None,
        )
        side = "buy" if record.decision.state == "confirmed" else "sell"
        order_id = f"entry-{index}" if side == "buy" else f"exit-{index}"
        if next_bar is None:
            orders.append(
                {
                    "id": order_id,
                    "side": side,
                    "mint": mint,
                    "status": "unfilled",
                    "reason": "no later quote",
                    "intended_at": record.at,
                }
            )
        else:
            planned.append((next_bar.available_at, index, record, next_bar))
    for _, index, record, next_bar in sorted(planned, key=lambda x: (x[0], x[1])):
        mint = record.pair.split(":", 1)[1]
        if record.decision.state == "confirmed":
            order_id = f"entry-{index}"
            reason = None
            if any(
                r.decision.state == "invalidated"
                and r.pair == record.pair
                and record.at < r.at <= next_bar.available_at
                for r in decisions
            ):
                reason = "invalidated before quote"
            elif mint in book.positions or len(book.positions) >= max_positions:
                reason = "position limit"
            latest = {
                bar.mint: bar
                for bar in ordered
                if bar.available_at <= next_bar.available_at and bar.close_at <= bar.available_at
            }
            if any(
                asset not in latest
                or next_bar.available_at - latest[asset].available_at > max_mark_age
                for asset in book.positions
            ):
                reason = "missing or stale position mark"
            else:
                equity = book.cash + sum(
                    (
                        quantity * latest[asset].close_usd
                        for asset, quantity in book.positions.items()
                    ),
                    Decimal(0),
                )
                if equity < initial_cash * (Decimal(1) - max_loss_fraction):
                    reason = "loss suspension"
            budget = min(
                book.cash * allocation_fraction, book.cash - initial_cash * reserve_fraction
            )
            if budget <= network_fee:
                reason = "stable reserve"
            if (
                next_bar.liquidity_usd is None
                or next_bar.liquidity_usd < budget * min_liquidity_multiple
            ):
                reason = "liquidity unavailable"
            if reason:
                orders.append(
                    {
                        "id": order_id,
                        "side": "buy",
                        "mint": mint,
                        "status": "unfilled",
                        "reason": reason,
                        "intended_at": record.at,
                    }
                )
                continue
            price = next_bar.close_usd * (Decimal(1) + impact_rate)
            quantity = (budget - network_fee) / (price + next_bar.close_usd * fee_rate)
            fee = quantity * next_bar.close_usd * fee_rate + network_fee
            book.buy(mint, quantity, price, fee, order_id)
            orders.append(
                {
                    "id": order_id,
                    "side": "buy",
                    "status": "filled",
                    "mint": mint,
                    "quantity": str(quantity),
                    "price": str(price),
                    "fee": str(fee),
                    "at": next_bar.available_at,
                    "intended_at": record.at,
                }
            )
        elif record.decision.state == "invalidated":
            if mint not in book.positions:
                continue
            quantity = book.positions[mint]
            price = next_bar.close_usd * (Decimal(1) - impact_rate)
            fee = quantity * next_bar.close_usd * fee_rate + network_fee
            book.sell(mint, quantity, price, fee, f"exit-{index}")
            orders.append(
                {
                    "id": f"exit-{index}",
                    "side": "sell",
                    "status": "filled",
                    "mint": mint,
                    "quantity": str(quantity),
                    "price": str(price),
                    "fee": str(fee),
                    "at": next_bar.available_at,
                    "intended_at": record.at,
                }
            )
    return PaperSimulation(book, tuple(orders))
