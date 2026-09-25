"""Deterministic paper ledger. No network or execution capability."""

from dataclasses import dataclass, field
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
) -> PaperSimulation:
    """Reserve-funded single-position policy. Next *available* bar is a quote proxy."""
    if (
        initial_cash < 0
        or not 0 < allocation_fraction <= 1
        or fee_rate < 0
        or impact_rate < 0
        or network_fee < 0
    ):
        raise ValueError("invalid paper policy")
    book = PaperBook(initial_cash)
    orders: list[dict] = []
    ordered = sorted(bars, key=lambda b: (b.available_at, b.close_at))
    for index, record in enumerate(decisions):
        if ":" not in record.pair:
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
        if record.decision.state == "confirmed" and mint not in book.positions:
            if next_bar is None:
                orders.append(
                    {
                        "id": f"entry-{index}",
                        "side": "buy",
                        "status": "unfilled",
                        "reason": "no later quote",
                    }
                )
                continue
            if any(
                r.decision.state == "invalidated"
                and r.pair == record.pair
                and record.at < r.at <= next_bar.available_at
                for r in decisions
            ):
                orders.append(
                    {
                        "id": f"entry-{index}",
                        "side": "buy",
                        "status": "unfilled",
                        "reason": "invalidated before quote",
                    }
                )
                continue
            budget = book.cash * allocation_fraction
            if (
                next_bar.liquidity_usd is None
                or next_bar.liquidity_usd < budget * min_liquidity_multiple
            ):
                orders.append(
                    {
                        "id": f"entry-{index}",
                        "side": "buy",
                        "status": "unfilled",
                        "reason": "liquidity unavailable",
                    }
                )
                continue
            price = next_bar.close_usd * (Decimal(1) + impact_rate)
            quantity = (budget - network_fee) / (price + next_bar.close_usd * fee_rate)
            fee = quantity * next_bar.close_usd * fee_rate + network_fee
            book.buy(mint, quantity, price, fee, f"entry-{index}")
            orders.append(
                {
                    "id": f"entry-{index}",
                    "side": "buy",
                    "status": "filled",
                    "mint": mint,
                    "quantity": str(quantity),
                    "price": str(price),
                    "fee": str(fee),
                    "at": next_bar.available_at,
                }
            )
        elif record.decision.state == "invalidated" and mint in book.positions:
            if next_bar is None:
                orders.append(
                    {
                        "id": f"exit-{index}",
                        "side": "sell",
                        "status": "unfilled",
                        "reason": "no later quote",
                    }
                )
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
                }
            )
    return PaperSimulation(book, tuple(orders))
