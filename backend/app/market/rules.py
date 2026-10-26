"""Exchange rules and data-quality checks the Risk Agent relies on.

- IDX auto-rejection limits (ARA / ARB) from the previous close
- market hours (IDX sessions in WIB, forex 24/5, crypto 24/7)
- data freshness: is the last candle recent enough to trade on?
- liquidity: average daily traded value and empty candles

IDX limits change often (2026: ARB cut to 7% on 19-20 Oct, planned symmetric from 2027), so the
numbers below are dated defaults and can be overridden with IDX_ARA_PCT / IDX_ARB_PCT in .env.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from ..risk import idx_tick

WIB = timezone(timedelta(hours=7))
INTERVAL_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}


# --------------------------------------------------------------------------- ARA / ARB
def _ara_pct(price: float) -> float:
    if price <= 200:
        return 0.35
    if price <= 5000:
        return 0.25
    return 0.20


def _env_pct(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) / 100 if raw else None
    except ValueError:
        return None


@dataclass
class PriceLimits:
    reference: float     # previous close
    ara: float           # highest price allowed today
    arb: float           # lowest price allowed today
    rule: str

    def to_dict(self) -> dict:
        return asdict(self)


def idx_price_limits(reference: float, on: date | None = None) -> PriceLimits:
    """Auto-rejection band for an IDX regular-board stock (Main/Development/New Economy boards).

    ARA: 35% (Rp<=200), 25% (Rp201-5,000), 20% (>Rp5,000).
    ARB until 31 Dec 2026: 7% (Rp1 for Rp11-14 stocks); from 2027 BEI plans ARB = ARA (symmetric).
    Acceleration / special-monitoring boards use other limits and are not modelled.
    """
    on = on or datetime.now(WIB).date()
    ara_pct = _env_pct("IDX_ARA_PCT") or _ara_pct(reference)
    arb_override = _env_pct("IDX_ARB_PCT")
    if arb_override is not None:
        arb_pct, rule = arb_override, f"ARB {arb_override:.0%} (override .env)"
    elif on < date(2027, 1, 1):
        arb_pct, rule = 0.07, "ARB 7% (BEI Okt 2026)"
    else:
        arb_pct, rule = _ara_pct(reference), "ARB simetris (rencana BEI 2027)"

    tick = idx_tick(reference)
    ara = math.floor(reference * (1 + ara_pct) / tick) * tick
    if arb_override is None and on < date(2027, 1, 1) and 11 <= reference <= 14:
        arb = reference - 1
        rule = "ARB Rp1 (saham Rp11–14, BEI Okt 2026)"
    else:
        arb = math.ceil(reference * (1 - arb_pct) / tick) * tick
    return PriceLimits(float(reference), float(ara), float(max(arb, 1)), f"ARA {ara_pct:.0%} · {rule}")


def _as_wib(ts: pd.Timestamp) -> pd.Timestamp:
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts).tz_convert(WIB)


def previous_close(df: pd.DataFrame, interval: str) -> float | None:
    """Close of the last *completed* trading day before the latest candle (IDX reference price)."""
    if df.empty:
        return None
    if interval == "1d":
        return float(df["close"].iloc[-2]) if len(df) >= 2 else None
    days = pd.Series([_as_wib(t).date() for t in df.index], index=df.index)
    last_day = days.iloc[-1]
    before = df[days < last_day]
    return float(before["close"].iloc[-1]) if len(before) else None


# --------------------------------------------------------------------------- market hours
def market_open(asset_class: str, now: datetime | None = None) -> tuple[bool, str]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if asset_class == "crypto":
        return True, "crypto 24/7"
    if asset_class == "idx_stock":
        w = now.astimezone(WIB)
        t = w.time()
        if w.weekday() >= 5:
            return False, "BEI tutup (akhir pekan)"
        friday = w.weekday() == 4
        s1_end = time(11, 30) if friday else time(12, 0)
        s2_start = time(14, 0) if friday else time(13, 30)
        if time(9, 0) <= t < s1_end or s2_start <= t < time(16, 0):
            return True, "sesi BEI berjalan"
        if s1_end <= t < s2_start:
            return False, "istirahat siang BEI"
        return False, "di luar jam bursa BEI (09:00–16:00 WIB)"
    # forex / metals: Sunday ~22:00 UTC to Friday ~22:00 UTC (DST shifts this by an hour)
    wd, hour = now.weekday(), now.hour
    if wd == 5 or (wd == 6 and hour < 22) or (wd == 4 and hour >= 22):
        return False, "pasar forex tutup (akhir pekan)"
    return True, "pasar forex buka"


@dataclass
class Freshness:
    last_candle: str
    age_minutes: float
    market_open: bool
    market_note: str
    stale: bool
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def freshness(df: pd.DataFrame, interval: str, asset_class: str, now: datetime | None = None) -> Freshness:
    now = now or datetime.now(timezone.utc)
    last = _as_wib(df.index[-1])
    age = max(0.0, (now - last.to_pydatetime()).total_seconds() / 60)
    is_open, note = market_open(asset_class, now)
    step = INTERVAL_MINUTES.get(interval, 15)
    # Allow a few missing bars (and Yahoo's delay) before calling the data stale
    limit = 4 * 1440 if interval == "1d" else max(3 * step, 45)
    stale = is_open and age > limit
    if stale:
        msg = f"Data basi: candle terakhir {age:.0f} menit lalu padahal pasar buka"
    elif not is_open:
        msg = f"{note.capitalize()}: plan memakai candle terakhir ({last:%d %b %H:%M} WIB); cek ulang saat pasar buka"
    else:
        msg = f"Data segar (candle terakhir {age:.0f} menit lalu)"
    return Freshness(last.isoformat(timespec="minutes"), round(age, 1), is_open, note, stale, msg)


# --------------------------------------------------------------------------- liquidity
@dataclass
class Liquidity:
    avg_daily_value: float      # in quote currency (IDR for IDX)
    days: int
    zero_volume_ratio: float    # share of candles with no trades
    level: str                  # ok | thin | illiquid | unknown
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def liquidity(df: pd.DataFrame, interval: str, asset_class: str) -> Liquidity:
    """Only meaningful for stocks: forex 'volume' from Yahoo is tick volume or zero."""
    if asset_class != "idx_stock" or df["volume"].sum() <= 0:
        return Liquidity(0.0, 0, 0.0, "unknown", "Volume tidak tersedia untuk instrumen ini")
    value = df["close"] * df["volume"]
    if interval == "1d":
        per_day = value
    else:
        days = [_as_wib(t).date() for t in df.index]
        per_day = value.groupby(days).sum()
    avg = float(per_day.tail(20).mean())
    zero = float((df["volume"] <= 0).mean())
    min_value = float(os.getenv("MIN_DAILY_VALUE_IDR", "1000000000"))
    warn_value = float(os.getenv("WARN_DAILY_VALUE_IDR", "5000000000"))
    if avg < min_value or zero > 0.5:
        level = "illiquid"
    elif avg < warn_value or zero > 0.2:
        level = "thin"
    else:
        level = "ok"
    text = (f"Nilai transaksi rata-rata Rp{avg / 1e9:,.2f} M/hari ({len(per_day)} hari), "
            f"{zero:.0%} candle tanpa transaksi")
    return Liquidity(avg, int(len(per_day)), round(zero, 3), level, text)
