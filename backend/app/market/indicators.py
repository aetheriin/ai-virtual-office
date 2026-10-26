"""Price-action facts the debate is built on: structure, S/R, volume, wicks, volatility.

Everything here is deterministic so Bull/Bear/Risk argue about the same numbers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class Swing:
    index: int
    price: float
    kind: str  # "high" | "low"


@dataclass
class MarketFacts:
    last_close: float
    last_time: str
    change_pct: float
    atr: float
    atr_pct: float
    ema20: float
    ema50: float
    structure: str              # bullish | bearish | ranging
    swing_highs: list[float]    # most recent last
    swing_lows: list[float]
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool
    support: float
    resistance: float
    support_held: bool
    breakout_up: bool           # close above last swing high
    breakdown: bool             # close below last swing low
    retest_up: bool             # broke resistance and retested from above
    upper_wick_rejection: bool
    lower_wick_rejection: bool
    liquidity_grab_up: bool     # wick above swing high then close back below
    volume_ratio: float         # recent avg / prior avg
    volume_trend: str           # rising | falling | flat

    def to_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def find_swings(df: pd.DataFrame, window: int = 3) -> list[Swing]:
    """Fractal swings: a bar whose high/low is the extreme of `window` bars on each side."""
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    swings: list[Swing] = []
    for i in range(window, len(df) - window):
        seg_h = highs[i - window : i + window + 1]
        seg_l = lows[i - window : i + window + 1]
        if highs[i] == seg_h.max():
            swings.append(Swing(i, float(highs[i]), "high"))
        if lows[i] == seg_l.min():
            swings.append(Swing(i, float(lows[i]), "low"))
    return swings


def compute_facts(df: pd.DataFrame) -> MarketFacts:
    if len(df) < 30:
        raise ValueError("Need at least 30 candles")
    close = df["close"]
    last = df.iloc[-1]
    a = atr(df)
    atr_now = float(a.iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

    swings = find_swings(df)
    sh = [s.price for s in swings if s.kind == "high"][-4:]
    sl = [s.price for s in swings if s.kind == "low"][-4:]
    if len(sh) < 2:
        sh = [float(df["high"].iloc[-30:-15].max()), float(df["high"].iloc[-15:].max())]
    if len(sl) < 2:
        sl = [float(df["low"].iloc[-30:-15].min()), float(df["low"].iloc[-15:].min())]

    hh, hl = sh[-1] > sh[-2], sl[-1] > sl[-2]
    lh, ll = sh[-1] < sh[-2], sl[-1] < sl[-2]
    if hh and hl:
        structure = "bullish"
    elif lh and ll:
        structure = "bearish"
    else:
        structure = "ranging"

    lc = float(last["close"])
    support = max([p for p in sl if p < lc], default=float(df["low"].tail(20).min()))
    resistance = min([p for p in sh if p > lc], default=float(df["high"].tail(20).max()))

    recent = df.tail(5)
    support_held = bool((recent["low"] >= support - 0.25 * atr_now).all())
    prev_close = float(df["close"].iloc[-2])
    last_sh, last_sl = sh[-1], sl[-1]
    breakout_up = lc > last_sh
    breakdown = lc < last_sl
    # Broke above the previous swing high within the last 10 bars and dipped back near it while holding
    window = df.tail(10)
    retest_up = bool(
        (window["close"] > sh[-2]).any() and lc > sh[-2] and window["low"].min() <= sh[-2] + 0.3 * atr_now
    )

    body = abs(last["close"] - last["open"])
    rng = max(float(last["high"] - last["low"]), 1e-12)
    upper_wick = float(last["high"] - max(last["close"], last["open"]))
    lower_wick = float(min(last["close"], last["open"]) - last["low"])
    upper_rej = upper_wick > max(body * 1.5, 0.4 * rng)
    lower_rej = lower_wick > max(body * 1.5, 0.4 * rng)
    liquidity_grab_up = bool((recent["high"] > last_sh).any() and lc < last_sh)

    vol = df["volume"]
    if vol.sum() > 0:
        rec_v = float(vol.tail(10).mean())
        prior_v = float(vol.iloc[-30:-10].mean()) or 1.0
        vr = rec_v / prior_v
    else:
        vr = 1.0
    vtrend = "rising" if vr > 1.15 else "falling" if vr < 0.85 else "flat"

    return MarketFacts(
        last_close=lc,
        last_time=str(df.index[-1]),
        change_pct=(lc / prev_close - 1) * 100,
        atr=atr_now,
        atr_pct=atr_now / lc * 100,
        ema20=ema20,
        ema50=ema50,
        structure=structure,
        swing_highs=[float(x) for x in sh],
        swing_lows=[float(x) for x in sl],
        higher_highs=bool(hh),
        higher_lows=bool(hl),
        lower_highs=bool(lh),
        lower_lows=bool(ll),
        support=float(support),
        resistance=float(resistance),
        support_held=support_held,
        breakout_up=bool(breakout_up),
        breakdown=bool(breakdown),
        retest_up=retest_up,
        upper_wick_rejection=bool(upper_rej),
        lower_wick_rejection=bool(lower_rej),
        liquidity_grab_up=liquidity_grab_up,
        volume_ratio=float(np.round(vr, 3)),
        volume_trend=vtrend,
    )


def candles_payload(df: pd.DataFrame, n: int = 80) -> list[dict]:
    """Compact OHLCV list for the frontend mini chart."""
    tail = df.tail(n)
    return [
        {"t": str(ts), "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close), "v": float(r.volume)}
        for ts, r in tail.iterrows()
    ]
