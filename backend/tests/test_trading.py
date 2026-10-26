import numpy as np
import pandas as pd

from app.agents.trading import bear_case, bull_case, judge, run_debate
from app.market.data import MarketData, resolve, synthetic_candles
from app.market.indicators import compute_facts


def _trend(up: bool, n: int = 120) -> pd.DataFrame:
    """Zig-zag trend with clear swings."""
    t = np.arange(n)
    base = 1000 + (t * 3 if up else -t * 3) + 25 * np.sin(t / 3)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min")
    vol = np.linspace(1e5, 3e5, n) if up else np.linspace(3e5, 1e5, n)
    return pd.DataFrame({"open": base - 1, "high": base + 6, "low": base - 6, "close": base + 1, "volume": vol}, index=idx)


def test_resolve_symbols():
    assert resolve("bbca").yf_ticker == "BBCA.JK"
    assert resolve("BBCA.JK").symbol == "BBCA"
    assert resolve("xau/usd").asset_class == "gold"


def test_uptrend_bull_outscores_bear():
    f = compute_facts(_trend(True))
    assert f.structure == "bullish"
    bull = bull_case(f, "idx_stock")
    bear = bear_case(f, "idx_stock", bull)
    assert bull.score > bear.score
    assert bull.stop_loss < bull.entry < bull.tp1 <= bull.tp2
    assert len(bear.risks) == 3


def test_downtrend_bear_levels_valid():
    f = compute_facts(_trend(False))
    assert f.structure == "bearish"
    bull = bull_case(f, "idx_stock")
    bear = bear_case(f, "idx_stock", bull)
    assert bear.score > bull.score
    assert bear.tp2 <= bear.tp1 < bear.entry < bear.stop_loss


def test_judge_vetoes_on_daily_loss():
    f = compute_facts(_trend(True))
    bull = bull_case(f, "idx_stock")
    bear = bear_case(f, "idx_stock", bull)
    plan = judge(f, bull, bear, capital=1e7, risk_pct=1, today_loss_pct=5, asset="idx_stock",
                 quote_ccy="IDR", account_ccy="IDR")
    assert plan["status"] == "WAIT"
    assert "VETO" in plan["reasons"][0]


def test_judge_wait_when_evidence_balanced():
    f = compute_facts(_trend(True))
    bull = bull_case(f, "idx_stock")
    bear = bear_case(f, "idx_stock", bull)
    bear.score = bull.score
    plan = judge(f, bull, bear, capital=1e7, risk_pct=1, today_loss_pct=0, asset="idx_stock",
                 quote_ccy="IDR", account_ccy="IDR")
    assert plan["status"] == "WAIT"


async def test_full_debate_offline_emits_and_returns_plan():
    events = []

    async def emit(ev, data):
        events.append((ev, data))

    md = MarketData(resolve("BBCA"), "15m", synthetic_candles("BBCA"), "synthetic")
    plan = await run_debate(md, emit, capital=1e7, risk_pct=1)
    assert plan["status"] in {"BUY", "SELL", "WAIT"}
    assert plan["demo"] is True
    speakers = [d["agent"] for e, d in events if e == "agent:message"]
    assert speakers == ["bull", "bear", "bull", "risk"]
