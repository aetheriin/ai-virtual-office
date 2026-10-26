"""Position sizing, tick rounding and Risk-to-Reward math (pure functions, fully tested)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

# Assumption (labelled in every plan): conversion rate used when the account is IDR
# but the instrument is quoted in USD. Override with USD_IDR_RATE in .env.
USD_IDR_RATE = float(os.getenv("USD_IDR_RATE", "16000"))

CONTRACT_SIZE = {"forex": 100_000, "gold": 100, "metal": 5_000, "crypto": 1}


def idx_tick(price: float) -> int:
    """IDX price fraction (tick size) by price band."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2_000:
        return 5
    if price < 5_000:
        return 10
    return 25


def round_price(price: float, asset_class: str, side: str = "nearest") -> float:
    if asset_class == "idx_stock":
        tick = idx_tick(price)
        fn = {"down": math.floor, "up": math.ceil}.get(side, round)
        return float(fn(price / tick) * tick)
    if asset_class == "forex":
        return round(price, 3 if price > 50 else 5)
    return round(price, 2)


def rr(entry: float, stop: float, target: float) -> float:
    risk = abs(entry - stop)
    return abs(target - entry) / risk if risk > 0 else 0.0


@dataclass
class PositionSize:
    quantity: float
    unit: str              # "lot (100 lembar)" | "lot" | "unit"
    risk_amount: float     # in account currency
    max_loss: float        # actual loss at SL with rounded quantity
    notional: float        # position value in account currency
    note: str = ""


def position_size(
    *,
    capital: float,
    risk_pct: float,
    entry: float,
    stop: float,
    asset_class: str,
    account_currency: str = "IDR",
    quote_currency: str = "USD",
) -> PositionSize:
    risk_amount = capital * risk_pct / 100
    dist = abs(entry - stop)
    if dist <= 0 or capital <= 0:
        return PositionSize(0, "unit", risk_amount, 0, 0, "Jarak SL tidak valid")

    if asset_class == "idx_stock":
        lots = math.floor(risk_amount / (dist * 100))
        affordable = math.floor(capital / (entry * 100))
        note = ""
        if lots > affordable:
            lots, note = affordable, "Dibatasi oleh modal (bukan oleh risiko)"
        return PositionSize(lots, "lot (100 lembar)", risk_amount, lots * 100 * dist, lots * 100 * entry,
                            note or ("Modal tidak cukup untuk 1 lot dengan risiko ini" if lots == 0 else ""))

    # Leveraged products: value of 1 price unit per lot, converted to account currency
    contract = CONTRACT_SIZE.get(asset_class, 1)
    fx = USD_IDR_RATE if (account_currency == "IDR" and quote_currency == "USD") else 1.0
    per_lot_loss = dist * contract * fx
    if asset_class == "forex" and entry > 50:  # JPY-quoted pair: P/L in quote ccy -> convert to USD
        per_lot_loss /= entry
    raw = risk_amount / per_lot_loss
    step = 1e-4 if asset_class == "crypto" else 0.01
    qty = math.floor(raw / step) * step
    note = ""
    if qty < step:
        note = f"Risiko per lot minimum melebihi {risk_pct}% modal; perkecil SL atau tambah modal"
    unit = "unit" if asset_class == "crypto" else "lot"
    notional = qty * contract * entry * (fx if asset_class != "forex" else 1)
    if fx != 1.0:
        note = (note + "; " if note else "") + f"Asumsi kurs USD/IDR = {USD_IDR_RATE:,.0f}"
    return PositionSize(round(qty, 4), unit, risk_amount, qty * per_lot_loss, notional, note)
