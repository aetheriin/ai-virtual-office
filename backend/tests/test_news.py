from datetime import datetime, timedelta, timezone

import pytest

from app.agents.trading import Proposal, bear_case, bull_case, judge, run_debate
from app.market import news as news_mod
from app.market.data import MarketData, resolve, synthetic_candles
from app.market.indicators import compute_facts
from app.market.news import (
    Headline, aggregate, lexicon_score, parse_alphavantage, parse_finnhub, parse_rss, parse_yfinance,
)
from tests.test_trading import _trend

NOW = datetime.now(timezone.utc)


def iso(hours_ago: float = 0) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def h(title: str, score: float, hours_ago: float = 1) -> Headline:
    return Headline(title, "test", "", iso(hours_ago), score)


@pytest.mark.parametrize("title,symbol,sign", [
    ("Fed signals rate cut as US economy weakens", "XAUUSD", +1),   # weaker USD -> gold up
    ("Fed signals rate cut as US economy weakens", "EURUSD", +1),   # weaker USD -> EURUSD up
    ("Fed signals rate cut as US economy weakens", "USDJPY", -1),   # USD is base -> down
    ("ECB turns hawkish, euro rallies", "EURUSD", +1),
    ("EUR/USD slides below 1.08", "EURUSD", -1),
    ("EUR/USD: Euro gains as dollar weakens", "EURUSD", +1),
    ("Gold slumps as dollar strength returns", "XAUUSD", -1),
    ("Dollar steady ahead of Fed decision", "EURUSD", 0),
    ("Gold climbs to record high on safe-haven demand", "XAUUSD", +1),
    ("Geopolitical tensions lift safe haven flows", "XAUUSD", +1),
    ("Bank Indonesia keeps BI rate, rupiah weakens", "USDIDR", +1),
    ("Australian retail sales beat expectations", "EURUSD", 0),       # irrelevant pair
])
def test_lexicon_direction(title, symbol, sign):
    s = lexicon_score(title, resolve(symbol))
    assert (s > 0) - (s < 0) == sign


def test_stock_headline_uses_plain_polarity():
    assert lexicon_score("BBCA laba kuartal III beats expectations, saham rallies", resolve("BBCA")) > 0


def test_aggregate_recency_weighting_and_labels():
    fresh_bear = [h("a", -0.8, 0.5), h("b", -0.6, 1)]
    stale_bull = [h("c", 1.0, 20), h("d", 1.0, 22)]
    s = aggregate("EURUSD", fresh_bear + stale_bull, ["rss"])
    assert s.label == "bearish" and s.score < 0
    assert aggregate("EURUSD", [], []).label == "no_data"
    assert aggregate("EURUSD", [h("x", 0.05)], []).label == "neutral"


def test_event_risk_flag():
    item = h("US Nonfarm payrolls beat expectations", 0.5, 1)
    item.high_impact = True
    assert aggregate("EURUSD", [item], []).event_risk


def test_parse_alphavantage_uses_per_currency_scores():
    payload = {"feed": [{
        "title": "Dollar slips after soft data", "url": "u", "source": "Reuters",
        "time_published": NOW.strftime("%Y%m%dT%H%M%S"),
        "ticker_sentiment": [
            {"ticker": "FOREX:USD", "relevance_score": "0.8", "ticker_sentiment_score": "-0.35"},
            {"ticker": "FOREX:EUR", "relevance_score": "0.5", "ticker_sentiment_score": "0.0"},
        ],
    }]}
    items = parse_alphavantage(payload, resolve("EURUSD"))
    assert items[0].method == "alphavantage"
    assert items[0].score == pytest.approx(1.0)  # USD bearish => EURUSD bullish


def test_parse_finnhub_filters_irrelevant():
    payload = [
        {"headline": "Yen jumps as BoJ hints at hike", "source": "X", "url": "u", "datetime": int(NOW.timestamp())},
        {"headline": "Oil inventories rise", "source": "X", "url": "u", "datetime": int(NOW.timestamp())},
    ]
    items = parse_finnhub(payload, resolve("USDJPY"))
    assert len(items) == 1 and items[0].score < 0


def test_parse_rss():
    xml = f"""<?xml version="1.0"?><rss><channel>
      <item><title>Gold slumps as dollar strength returns</title><link>https://x/1</link>
      <pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>
      <item><title>Unrelated sports story</title><link>https://x/2</link></item>
    </channel></rss>"""
    items = parse_rss(xml, resolve("XAUUSD"), "fxstreet")
    assert len(items) == 1 and items[0].score < 0
    assert parse_rss("not xml", resolve("XAUUSD"), "x") == []


def test_parse_yfinance_both_shapes():
    new = [{"content": {"title": "BBCA rallies on strong earnings", "pubDate": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "provider": {"displayName": "Bisnis"}, "canonicalUrl": {"url": "https://b"}}}]
    old = [{"title": "BBCA slides after downgrade", "providerPublishTime": int(NOW.timestamp()), "publisher": "Kontan", "link": "https://k"}]
    a, b = parse_yfinance(new, resolve("BBCA"))[0], parse_yfinance(old, resolve("BBCA"))[0]
    assert a.score > 0 and a.source == "Bisnis"
    assert b.score < 0 and b.url == "https://k"


async def test_load_news_merges_dedupes_and_survives_failures(monkeypatch):
    async def ok(client, inst):
        return [h("Dollar weakens after Fed cut", 0.7), h("Dollar weakens after Fed cut!", 0.7), h("Old news", 0.9, 100)]

    async def boom(client, inst):
        raise RuntimeError("network down")

    async def none(*a):
        return []

    monkeypatch.setattr(news_mod, "_fetch_alphavantage", boom)
    monkeypatch.setattr(news_mod, "_fetch_finnhub", ok)
    monkeypatch.setattr(news_mod, "_fetch_rss", none)
    monkeypatch.setattr(news_mod, "_fetch_yfinance", none)
    s = await news_mod.load_news(resolve("EURUSD"))
    assert s.sources == ["finnhub"]
    assert len(s.headlines) == 1  # duplicate + stale removed
    assert s.label == "bullish"


def _sentiment(score: float, n: int = 4):
    return aggregate("EURUSD", [h(f"t{i}", score) for i in range(n)], ["test"])


def test_news_adds_bounded_evidence_to_matching_side():
    f = compute_facts(_trend(True))
    base = bull_case(f, "forex")
    boosted = bull_case(f, "forex", _sentiment(0.9))
    assert 0 < boosted.score - base.score <= 1.5
    assert any("Sentimen berita bullish" in e for e in boosted.evidence)
    assert bear_case(f, "forex", base, _sentiment(0.9)).score == bear_case(f, "forex", base).score


def test_strong_opposing_news_vetoes_trade():
    f = compute_facts(_trend(True))
    bull = Proposal("LONG", 6, ["x"], entry=1.10, stop_loss=1.09, tp1=1.115, tp2=1.13, trigger="t")
    bear = Proposal("SHORT", 0, ["y"], entry=1.10, stop_loss=1.11, tp1=1.09, tp2=1.08, trigger="t", risks=["a", "b", "c"])
    args = dict(capital=1e5, risk_pct=1, today_loss_pct=0, asset="forex", quote_ccy="USD", account_ccy="USD")
    assert judge(f, bull, bear, **args)["status"] == "BUY"
    assert judge(f, bull, bear, news=_sentiment(0.8), **args)["status"] == "BUY"
    plan = judge(f, bull, bear, news=_sentiment(-0.8), **args)
    assert plan["status"] == "WAIT"
    assert any("sentimen berita kuat" in r for r in plan["reasons"])
    # weak opposing news (only 2 headlines) is a warning for the Bear, not a veto
    assert judge(f, bull, bear, news=_sentiment(-0.8, n=2), **args)["status"] == "BUY"


async def test_debate_includes_news_in_plan():
    events = []

    async def emit(ev, data):
        events.append((ev, data))

    md = MarketData(resolve("EURUSD"), "15m", synthetic_candles("EURUSD", start_price=1.1), "synthetic")
    plan = await run_debate(md, emit, capital=1e4, risk_pct=1, account_currency="USD", news=_sentiment(0.6))
    assert plan["news"]["label"] == "bullish"
    assert any("Sentimen berita bullish" in e for e in plan["bull"]["evidence"])
