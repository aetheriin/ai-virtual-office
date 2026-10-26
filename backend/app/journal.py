"""Paper-trading journal: every BUY/SELL plan is tracked against later candles, so the strategy's
real hit rate and R-multiple become visible before any money is at risk.

Trade management model (simple and conservative):
- filled at the plan's entry when the plan is made (market order)
- half the position exits at TP1, the stop on the rest moves to break-even, the rest targets TP2
- if one candle touches both the stop and a target, the stop is assumed to hit first
- an open trade expires after JOURNAL_EXPIRY_HOURS (intraday) / JOURNAL_EXPIRY_DAYS (1d) and closes at the last price
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

EXPIRY_HOURS = float(os.getenv("JOURNAL_EXPIRY_HOURS", "48"))
EXPIRY_DAYS = float(os.getenv("JOURNAL_EXPIRY_DAYS", "10"))


@dataclass
class Outcome:
    status: str                 # open | tp1 (half closed, rest running) | closed
    result: str | None          # tp2 | tp1_be | sl | expired
    r_multiple: float | None    # realised R when closed
    exit_price: float | None
    closed_at: str | None
    tp1_hit: bool


def expiry_for(opened_at: datetime, interval: str) -> datetime:
    return opened_at + (timedelta(days=EXPIRY_DAYS) if interval == "1d" else timedelta(hours=EXPIRY_HOURS))


def _ts(t) -> datetime:
    ts = pd.Timestamp(t)
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts).to_pydatetime()


def evaluate(trade: dict, candles: pd.DataFrame, now: datetime | None = None) -> Outcome:
    """Replay candles after `trade['opened_at']`. `trade` needs side, entry, stop_loss, tp1, tp2, opened_at, interval."""
    now = now or datetime.now(timezone.utc)
    side = 1 if trade["side"] == "LONG" else -1
    entry, sl, tp1, tp2 = (float(trade[k]) for k in ("entry", "stop_loss", "tp1", "tp2"))
    risk = abs(entry - sl) or 1e-12
    r1, r2 = abs(tp1 - entry) / risk, abs(tp2 - entry) / risk
    opened = _ts(trade["opened_at"])
    expires = expiry_for(opened, trade.get("interval", "15m"))
    tp1_hit = bool(trade.get("tp1_hit"))

    def hit_stop(bar, level) -> bool:
        return bar.low <= level if side > 0 else bar.high >= level

    def hit_target(bar, level) -> bool:
        return bar.high >= level if side > 0 else bar.low <= level

    last_price = None
    for t, bar in candles.iterrows():
        ts = _ts(t)
        if ts <= opened:
            continue
        if ts > expires:
            break
        last_price = float(bar.close)
        stop = entry if tp1_hit else sl
        if hit_stop(bar, stop):  # pessimistic: stop before target inside one candle
            if tp1_hit:
                return Outcome("closed", "tp1_be", round(0.5 * r1, 3), entry, ts.isoformat(), True)
            return Outcome("closed", "sl", -1.0, sl, ts.isoformat(), False)
        if hit_target(bar, tp2):
            return Outcome("closed", "tp2", round(0.5 * r1 + 0.5 * r2, 3), tp2, ts.isoformat(), True)
        if not tp1_hit and hit_target(bar, tp1):
            tp1_hit = True

    if now >= expires and last_price is not None:
        move = side * (last_price - entry) / risk
        r = 0.5 * r1 + 0.5 * move if tp1_hit else move
        return Outcome("closed", "expired", round(r, 3), last_price, expires.isoformat(), tp1_hit)
    if now >= expires and last_price is None:
        return Outcome("closed", "expired", 0.0, entry, expires.isoformat(), tp1_hit)
    return Outcome("tp1" if tp1_hit else "open", None, None, None, None, tp1_hit)


def stats(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["status"] == "closed" and t["r_multiple"] is not None]
    wins = [t for t in closed if t["r_multiple"] > 0]
    total_r = sum(t["r_multiple"] for t in closed)
    by_source: dict[str, dict] = {}
    for t in closed:
        b = by_source.setdefault(t.get("source") or "analisa", {"closed": 0, "wins": 0, "total_r": 0.0})
        b["closed"] += 1
        b["wins"] += t["r_multiple"] > 0
        b["total_r"] = round(b["total_r"] + t["r_multiple"], 3)
    pnl = sum((t["r_multiple"] or 0) * (t.get("risk_amount") or 0) for t in closed)
    return {
        "total": len(trades),
        "open": sum(t["status"] != "closed" for t in trades),
        "closed": len(closed),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "avg_r": round(total_r / len(closed), 3) if closed else None,
        "total_r": round(total_r, 3),
        "paper_pnl": round(pnl, 2),
        "by_source": by_source,
        "note": "Butuh minimal ~30 trade tertutup sebelum angka ini berarti." if len(closed) < 30 else "",
    }
