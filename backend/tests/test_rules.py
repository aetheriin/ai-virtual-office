from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.agents.trading import MarketContext, Proposal, cap_to_limits, judge
from app.market.indicators import compute_facts
from app.market.rules import WIB, freshness, idx_price_limits, liquidity, market_open, previous_close
from tests.test_trading import _trend

OCT_2026 = date(2026, 10, 26)


@pytest.mark.parametrize("ref,ara,arb", [
    (100, 135, 93),      # Rp<=200: ARA 35%, ARB 7%; tick Rp1
    (13, 17, 12),        # Rp11-14: ARB is Rp1
    (1000, 1250, 930),   # Rp201-5000: ARA 25%; tick Rp5
    (9000, 10800, 8375), # >Rp5000: ARA 20%; tick Rp25, ARB rounded up to the tick
])
def test_idx_limits_oct_2026(ref, ara, arb):
    lim = idx_price_limits(ref, OCT_2026)
    assert (lim.ara, lim.arb) == (ara, arb)


def test_idx_limits_2027_symmetric_and_override(monkeypatch):
    assert idx_price_limits(1000, date(2027, 1, 5)).arb == 750
    monkeypatch.setenv("IDX_ARB_PCT", "15")
    lim = idx_price_limits(1000, OCT_2026)
    assert lim.arb == 850 and "override" in lim.rule


def _candles(start_wib: datetime, n: int, step_min=15, price=1000.0, vol=1e6):
    idx = pd.date_range(start_wib, periods=n, freq=f"{step_min}min")
    return pd.DataFrame({"open": price, "high": price + 5, "low": price - 5, "close": price, "volume": vol}, index=idx)


def test_previous_close_uses_last_completed_day():
    day1 = _candles(datetime(2026, 10, 22, 9, 0, tzinfo=WIB), 20, price=1000)
    day1.iloc[-1, day1.columns.get_loc("close")] = 1010
    day2 = _candles(datetime(2026, 10, 23, 9, 0, tzinfo=WIB), 10, price=1100)
    assert previous_close(pd.concat([day1, day2]), "15m") == 1010
    assert previous_close(day2, "15m") is None


@pytest.mark.parametrize("wib,open_", [
    (datetime(2026, 10, 26, 10, 0), True),    # Monday session 1
    (datetime(2026, 10, 26, 12, 30), False),  # lunch break
    (datetime(2026, 10, 30, 13, 45), False),  # Friday break lasts until 14:00
    (datetime(2026, 10, 30, 14, 5), True),
    (datetime(2026, 10, 26, 16, 30), False),  # after close
    (datetime(2026, 10, 31, 10, 0), False),   # Saturday
])
def test_idx_market_hours(wib, open_):
    assert market_open("idx_stock", wib.replace(tzinfo=WIB))[0] is open_


def test_forex_hours():
    sat = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    mon = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    assert market_open("forex", sat)[0] is False and market_open("forex", mon)[0] is True
    assert market_open("crypto", sat)[0] is True


def test_freshness_stale_only_while_market_open():
    df = _candles(datetime(2026, 10, 26, 9, 0, tzinfo=WIB), 4)  # last candle 09:45 WIB
    now_open = datetime(2026, 10, 26, 11, 30, tzinfo=WIB)
    assert freshness(df, "15m", "idx_stock", now_open).stale is True
    after_close = datetime(2026, 10, 26, 19, 0, tzinfo=WIB)
    f = freshness(df, "15m", "idx_stock", after_close)
    assert f.stale is False and not f.market_open and "cek ulang" in f.note
    assert freshness(df, "15m", "idx_stock", datetime(2026, 10, 26, 10, 10, tzinfo=WIB)).stale is False


def test_liquidity_levels(monkeypatch):
    start = datetime(2026, 10, 20, 9, 0, tzinfo=WIB)
    liquid = _candles(start, 60, price=1000, vol=1e6)     # Rp1 M per candle
    assert liquidity(liquid, "15m", "idx_stock").level == "ok"
    thin = _candles(start, 60, price=100, vol=1e5)        # Rp10 jt per candle
    assert liquidity(thin, "15m", "idx_stock").level == "illiquid"
    dead = liquid.copy()
    dead.loc[dead.index[::2], "volume"] = 0               # half the candles empty
    assert liquidity(dead, "15m", "idx_stock").level in {"thin", "illiquid"}
    assert liquidity(liquid, "15m", "forex").level == "unknown"


# --------------------------------------------------------------------------- judge integration
F = compute_facts(_trend(True))
ARGS = dict(capital=1e8, risk_pct=1, today_loss_pct=0, quote_ccy="IDR", account_ccy="IDR")


def _long(entry=1000, sl=950, tp1=1080, tp2=1150):
    return Proposal("LONG", 6, ["x"], entry=entry, stop_loss=sl, tp1=tp1, tp2=tp2, trigger="t")


def _short(score=0):
    return Proposal("SHORT", score, ["y"], entry=1000, stop_loss=1050, tp1=920, tp2=850, trigger="t", risks=["a", "b", "c"])


def test_tp_capped_at_ara():
    lim = idx_price_limits(1000, OCT_2026)  # ARA 1250
    p = cap_to_limits(_long(entry=1200, sl=1150, tp1=1300, tp2=1400), lim, "idx_stock")
    assert p.tp1 == 1250 and p.tp2 == 1250 and any("ARA" in n for n in p.notes)


def test_stock_bearish_bias_is_avoid_not_short():
    plan = judge(F, _long(), _short(score=10), asset="idx_stock", **ARGS)
    assert plan["status"] == "WAIT" and plan["bias"] == "SHORT"
    assert "Short tidak tersedia" in plan["reasons"][0]
    assert plan["position"]["quantity"] == 0
    forex = judge(F, _long(), _short(score=10), asset="forex", **{**ARGS, "quote_ccy": "USD", "account_ccy": "USD"})
    assert forex["bias"] == "SHORT"  # forex can still short


def test_stale_and_illiquid_veto():
    df = _candles(datetime(2026, 10, 26, 9, 0, tzinfo=WIB), 4)
    stale = MarketContext(fresh=freshness(df, "15m", "idx_stock", datetime(2026, 10, 26, 11, 30, tzinfo=WIB)))
    plan = judge(F, _long(), _short(), asset="idx_stock", ctx=stale, **ARGS)
    assert plan["status"] == "WAIT" and "basi" in plan["reasons"][0]

    thin = _candles(datetime(2026, 10, 20, 9, 0, tzinfo=WIB), 60, price=100, vol=1e5)
    plan = judge(F, _long(), _short(), asset="idx_stock", ctx=MarketContext(liq=liquidity(thin, "15m", "idx_stock")), **ARGS)
    assert plan["status"] == "WAIT" and "tidak likuid" in plan["reasons"][0]


def test_clean_long_passes_with_warnings_attached():
    df = _candles(datetime(2026, 10, 20, 9, 0, tzinfo=WIB), 60, price=1000, vol=1e6)
    closed = freshness(df, "15m", "idx_stock", datetime(2026, 10, 25, 10, 0, tzinfo=WIB))  # Sunday
    ctx = MarketContext(limits=idx_price_limits(1000, OCT_2026), fresh=closed, liq=liquidity(df, "15m", "idx_stock"))
    plan = judge(F, _long(), _short(), asset="idx_stock", ctx=ctx, **ARGS)
    assert plan["status"] == "BUY"
    assert any("cek ulang saat pasar buka" in w for w in plan["warnings"])
    assert plan["limits"]["ara"] == 1250 and plan["liquidity"]["level"] == "ok"
