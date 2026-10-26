import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
import pytest

from app import main
from app.market import data as data_mod
from app.market.data import MarketData, resolve
from app.screener import analyse_stock


def uptrend(n=111, start=1000.0, vol=2e6, step="1D"):
    """Zig-zag uptrend that ends in a pullback towards support: a textbook BUY setup.

    (n=111 is chosen on purpose: most other endings sit just under the last swing high,
    where the Risk Agent correctly vetoes because TP1 is closer than 1R.)
    """
    k = start / 1000
    t = np.arange(n)
    base = start + t * 3 * k + 25 * k * np.sin(t / 3)
    idx = pd.date_range(end=pd.Timestamp.now("UTC").floor("D"), periods=n, freq=step)
    return pd.DataFrame({"open": base - k, "high": base + 6 * k, "low": base - 6 * k, "close": base + k, "volume": vol}, index=idx)


def downtrend(n=120):
    df = uptrend(n, start=1000)
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].iloc[::-1].to_numpy()
    return df


@pytest.fixture
def market(monkeypatch, patch_settings):
    """BUY on BBCA/TLKM, illiquid BUVA, bearish BUMI, unknown XXXX."""
    patch_settings(allow_synthetic_data=False)
    series = {"BBCA": uptrend(start=9000), "TLKM": uptrend(113, start=3000), "BUVA": uptrend(start=100, vol=1000),
              "BUMI": downtrend()}
    monkeypatch.setattr(data_mod, "_download_many", lambda insts, interval: {i.symbol: series[i.symbol] for i in insts if i.symbol in series})
    for name in ("_from_mt5", "_from_yfinance", "_from_twelvedata"):
        monkeypatch.setattr(data_mod, name, lambda inst, interval: series.get(inst.symbol))
    return series


@pytest.fixture
async def client(monkeypatch, tmp_path):
    events = []

    async def capture(event, data=None, **k):
        events.append((event, data))
    monkeypatch.setattr(main.sio, "emit", capture)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(main.asyncio, "sleep", lambda s: real_sleep(0))  # skip the avatar pacing
    monkeypatch.setattr(main, "store", main.Store(str(tmp_path / "office.db")))
    await main.projects.init()
    main._running.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        c.events = events
        yield c


async def _wait_event(client, name, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        for ev, data in client.events:
            if ev == name:
                return data
        await asyncio.sleep(0.01)
    raise AssertionError(f"no {name} event; got {[e for e, _ in client.events]}")


def test_analyse_stock_buy_candidate(market):
    md = MarketData(resolve("BBCA"), "1d", market["BBCA"], "yfinance")
    row = analyse_stock(md, capital=1e8, risk_pct=1)
    assert row["status"] == "BUY" and row["limits"]["ara"] > row["price"]
    assert row["tp2"] <= row["limits"]["ara"] and row["position"]["quantity"] > 0
    assert row["summary"].startswith("Beli di sekitar")


async def test_screener_ranks_and_journals(client, market):
    r = await client.post("/api/screener/run", json={"interval": "1d", "symbols": ["BBCA", "TLKM", "BUVA", "BUMI", "XXXX"],
                                                     "capital": 1e8, "risk_pct": 1})
    assert r.status_code == 202
    result = await _wait_event(client, "screener:result")
    recs = [x["symbol"] for x in result["recommendations"]]
    assert set(recs) == {"BBCA", "TLKM"}
    assert "BUVA" not in recs and "BUMI" in result["avoid"]
    assert "XXXX" in result["errors"] and result["scanned"] == 4
    assert result["journaled"] == recs[:3]
    assert (await client.get("/api/screener/last")).json()["id"] == result["id"]
    j = (await client.get("/api/journal")).json()
    assert j["stats"]["open"] == 2 and {t["source"] for t in j["trades"]} == {"screener"}
    assert "it" not in main._running and "screener" not in main._running


async def test_screener_universe_validation(client):
    assert (await client.get("/api/screener/universe")).json()["symbols"][0] == "BBCA"
    assert (await client.put("/api/screener/universe", json={"symbols": ["XAUUSD"]})).status_code == 422
    assert (await client.put("/api/screener/universe", json={"symbols": ["bad;sym"]})).status_code == 422
    r = await client.put("/api/screener/universe", json={"symbols": ["buva", "BUMI.JK", "BUVA"]})
    assert r.json()["symbols"] == ["BUVA", "BUMI"]


async def test_watchlist_api(client):
    assert (await client.get("/api/watchlist")).json()["symbols"][0] == "BBCA"
    r = await client.put("/api/watchlist", json={"symbols": ["BUVA", "bumi", "xauusd"]})
    assert r.json()["symbols"] == ["BUVA", "BUMI", "XAUUSD"]


async def test_unknown_ticker_reports_error(client, market):
    r = await client.post("/api/trade/analyze", json={"symbol": "BUAV", "interval": "1d"})
    assert r.status_code == 202
    err = await _wait_event(client, "job:error")
    assert "tidak ditemukan" in err["error"]


async def test_analysis_buy_goes_to_journal_and_refresh(client, market):
    await client.post("/api/trade/analyze", json={"symbol": "BBCA", "interval": "1d", "capital": 1e8})
    plan = await _wait_event(client, "trade:plan")
    assert plan["status"] == "BUY" and plan["paper_trade_id"]
    j = (await client.get("/api/journal")).json()
    assert j["trades"][0]["source"] == "analisa" and j["trades"][0]["status"] == "open"
    res = (await client.post("/api/journal/refresh")).json()
    assert res["checked"] == 1 and res["errors"] == {}
    assert (await client.delete(f"/api/journal/{j['trades'][0]['id']}")).status_code == 204


async def test_screener_and_arena_do_not_overlap(client, market):
    main._running.add("screener")
    r = await client.post("/api/trade/analyze", json={"symbol": "BBCA", "interval": "1d"})
    assert r.status_code == 409
    main._running.clear()
    main._running.add("trade")
    assert (await client.post("/api/screener/run", json={})).status_code == 409
