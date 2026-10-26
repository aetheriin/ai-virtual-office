from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app import paper
from app.db import Store
from app.journal import evaluate, stats
from app.market.data import MarketData, resolve

T0 = datetime(2026, 10, 26, 3, 0, tzinfo=timezone.utc)
LONG = {"side": "LONG", "entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "opened_at": T0.isoformat(), "interval": "15m"}


def bars(*hl, start=T0):
    """Candles from (high, low[, close]) tuples, 15 minutes apart, starting after the open."""
    rows = [{"open": (h + l) / 2, "high": h, "low": l, "close": (c[0] if c else (h + l) / 2), "volume": 1}
            for h, l, *c in hl]
    idx = [start + timedelta(minutes=15 * (i + 1)) for i in range(len(rows))]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def test_tp2_after_tp1():
    out = evaluate(LONG, bars((101, 99), (106, 100.5), (111, 104)), T0 + timedelta(hours=2))
    assert (out.status, out.result, out.r_multiple) == ("closed", "tp2", 1.5)  # 0.5*1 + 0.5*2


def test_stop_loss():
    out = evaluate(LONG, bars((101, 99), (100, 94)), T0 + timedelta(hours=2))
    assert (out.result, out.r_multiple) == ("sl", -1.0)


def test_break_even_after_tp1():
    out = evaluate(LONG, bars((106, 101), (103, 99.5)), T0 + timedelta(hours=2))
    assert (out.result, out.r_multiple) == ("tp1_be", 0.5)


def test_same_candle_stop_and_target_is_a_loss():
    out = evaluate(LONG, bars((112, 94)), T0 + timedelta(hours=1))
    assert out.result == "sl"


def test_still_open_then_expired():
    assert evaluate(LONG, bars((103, 98)), T0 + timedelta(hours=1)).status == "open"
    assert evaluate(LONG, bars((106, 101)), T0 + timedelta(hours=1)).status == "tp1"
    out = evaluate(LONG, bars((103, 98, 102)), T0 + timedelta(hours=49))
    assert (out.result, out.r_multiple) == ("expired", 0.4)  # (102-100)/5


def test_candles_before_open_are_ignored():
    early = bars((120, 90), start=T0 - timedelta(hours=2))
    assert evaluate(LONG, early, T0 + timedelta(minutes=30)).status == "open"


def test_short_mirror():
    short = {**LONG, "side": "SHORT", "stop_loss": 105, "tp1": 95, "tp2": 90}
    out = evaluate(short, bars((100, 94), (96, 89)), T0 + timedelta(hours=2))
    assert (out.result, out.r_multiple) == ("tp2", 1.5)


def test_stats():
    trades = [{"status": "closed", "r_multiple": 1.5, "risk_amount": 100, "source": "analisa"},
              {"status": "closed", "r_multiple": -1.0, "risk_amount": 100, "source": "screener"},
              {"status": "open", "r_multiple": None}]
    s = stats(trades)
    assert s["closed"] == 2 and s["open"] == 1 and s["win_rate"] == 0.5 and s["total_r"] == 0.5
    assert s["paper_pnl"] == 50 and s["by_source"]["screener"]["total_r"] == -1.0 and s["note"]


PLAN = {"status": "BUY", "symbol": "BBCA", "asset_class": "idx_stock", "interval": "15m", "entry": 100, "stop_loss": 95,
        "tp1": 105, "tp2": 110, "position": {"quantity": 10, "unit": "lot", "max_loss": 5000}, "demo": False}


async def test_record_and_refresh(tmp_path):
    store = Store(str(tmp_path / "o.db"))
    assert paper.record_plan(store, {**PLAN, "status": "WAIT"}) is None
    assert paper.record_plan(store, {**PLAN, "demo": True}) is None
    tid = paper.record_plan(store, PLAN, source="screener")
    trade = store.paper_trades()[0]
    assert trade["id"] == tid and trade["side"] == "LONG" and trade["source"] == "screener"

    opened = datetime.fromisoformat(trade["opened_at"])

    async def load(symbol, interval):
        return MarketData(resolve(symbol), interval, bars((106, 101), (111, 105), start=opened), "yfinance")

    res = await paper.refresh(store, load)
    assert res == {"checked": 1, "closed": 1, "errors": {}}
    t = store.paper_trades()[0]
    assert t["status"] == "closed" and t["result"] == "tp2" and t["r_multiple"] == 1.5

    async def synthetic(symbol, interval):
        return MarketData(resolve(symbol), interval, bars((90, 80), start=opened), "synthetic")

    paper.record_plan(store, PLAN)
    assert (await paper.refresh(store, synthetic))["checked"] == 0  # never scored on fake data

    async def boom(symbol, interval):
        raise LookupError("tidak ditemukan")

    assert (await paper.refresh(store, boom))["errors"] == {"BBCA": "tidak ditemukan"}


def test_watchlist_defaults_and_settings(tmp_path):
    store = Store(str(tmp_path / "o.db"))
    assert store.watchlist()[:2] == ["BBCA", "BBRI"]
    store.set_watchlist(["BUVA", "BUMI", "BUVA"])
    assert store.watchlist() == ["BUVA", "BUMI"]
    store.set_watchlist([])
    assert store.watchlist() == []  # an emptied list stays empty (no re-seeding)
    store.set_setting("x", {"a": [1]})
    assert store.get_setting("x") == {"a": [1]} and store.get_setting("missing") is None
