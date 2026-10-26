"""Forex / stock news sentiment as extra evidence for the Bull/Bear debate.

Sources (first ones that answer are merged, duplicates removed):
    1. Alpha Vantage NEWS_SENTIMENT  (ALPHA_VANTAGE_API_KEY) - per-currency sentiment scores
    2. Finnhub forex news            (FINNHUB_API_KEY)
    3. RSS feeds                     (NEWS_RSS_FEEDS, no key needed)
    4. yfinance ticker news          (IDX stocks, no key needed)

Scoring is directional for the instrument: for a pair BASE/QUOTE the headline
score is sentiment(BASE) - sentiment(QUOTE), so "Fed turns dovish" is bearish
USD and therefore bullish for XAUUSD / EURUSD and bearish for USDJPY.
Per-headline scores come from Alpha Vantage, the LLM, or a keyword lexicon
(in that order). Aggregation is a recency-weighted mean in [-1, 1].
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..config import settings
from ..llm import chat, extract_json
from .data import Instrument

log = logging.getLogger(__name__)

HALF_LIFE_HOURS = 6.0
BULLISH_AT = 0.15
STRONG_AT = 0.4
MAX_ITEMS = 40

# Words that tie a headline to a currency / asset
CURRENCY_KEYWORDS: dict[str, list[str]] = {
    "USD": ["usd", "dollar", "greenback", "fed", "fomc", "powell", "u.s.", "us economy", "treasury", "nonfarm", "payrolls", "nfp", "dxy", "wall street"],
    "EUR": ["eur", "euro", "ecb", "lagarde", "eurozone", "euro area", "germany", "german"],
    "GBP": ["gbp", "pound", "sterling", "cable", "boe", "bank of england", "bailey", "uk economy", "britain"],
    "JPY": ["jpy", "yen", "boj", "bank of japan", "ueda", "japan"],
    "AUD": ["aud", "aussie", "rba", "reserve bank of australia", "australia"],
    "IDR": ["idr", "rupiah", "bank indonesia", "bi rate", "indonesia"],
    "XAU": ["gold", "xau", "bullion"],
    "XAG": ["silver", "xag"],
    "BTC": ["bitcoin", "btc", "crypto"],
}

# Polarity for the currency/asset a headline is about
POSITIVE = [
    "hawkish", "rate hike", "hikes", "raises rates", "strong", "stronger", "strength", "beats", "beat expectations",
    "surge", "surges", "rally", "rallies", "gain", "gains", "jumps", "climbs", "rises", "rebound", "firm", "firmer",
    "strengthens", "advances", "soars", "spikes", "recovers", "extends gains",
    "robust", "upbeat", "higher than expected", "hotter than expected", "record high", "bullish", "upgrade", "outperform",
]
NEGATIVE = [
    "dovish", "rate cut", "cuts rates", "cut rates", "weak", "weaker", "weakness", "misses", "miss expectations",
    "slump", "slumps", "falls", "drops", "slides", "slips", "declines", "plunge", "plunges", "tumble", "tumbles",
    "recession", "contraction", "lower than expected", "cooler than expected", "softer", "bearish", "downgrade",
    "sell-off", "selloff", "underperform", "losses", "default", "weakens", "eases", "softens", "sinks", "retreats",
    "extends losses", "pressured", "under pressure",
]
# Risk-off language lifts safe havens (gold, yen) and hurts risk assets
RISK_OFF = ["safe haven", "safe-haven", "geopolitical", "tensions", "war", "conflict", "uncertainty", "risk aversion", "risk-off"]
SAFE_HAVENS = {"XAU": 1.0, "JPY": 0.6, "XAG": 0.5, "USD": 0.3}

HIGH_IMPACT = [
    "nonfarm", "payrolls", "nfp", "fomc", "rate decision", "interest rate decision", "cpi", "inflation data",
    "gdp", "ecb decision", "boj decision", "boe decision", "fed decision", "jackson hole", "bi rate decision",
]


@dataclass
class Headline:
    title: str
    source: str
    url: str
    published: str          # ISO-8601 UTC
    score: float = 0.0      # directional for the instrument, -1..1
    method: str = "lexicon"  # alphavantage | llm | lexicon
    high_impact: bool = False

    @property
    def age_hours(self) -> float:
        try:
            ts = datetime.fromisoformat(self.published)
        except ValueError:
            return 24.0
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 3600)


@dataclass
class NewsSentiment:
    symbol: str
    score: float                    # -1 (bearish) .. +1 (bullish)
    label: str                      # bullish | bearish | neutral | no_data
    count: int
    sources: list[str]
    event_risk: bool                # high-impact release in the last few hours
    headlines: list[Headline] = field(default_factory=list)

    @property
    def strong(self) -> bool:
        return abs(self.score) >= STRONG_AT and self.count >= 3

    @property
    def usable(self) -> bool:
        return self.count >= 2 and self.label in {"bullish", "bearish"}

    def top(self, n: int = 3, side: int = 0) -> list[Headline]:
        items = [h for h in self.headlines if side == 0 or h.score * side > 0]
        return sorted(items, key=lambda h: abs(h.score), reverse=True)[:n]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(self.score, 3)
        d["strong"] = self.strong
        d["headlines"] = [asdict(h) | {"score": round(h.score, 2)} for h in self.headlines[:15]]
        return d


def empty(symbol: str) -> NewsSentiment:
    return NewsSentiment(symbol, 0.0, "no_data", 0, [], False, [])


# --------------------------------------------------------------------------- instrument legs
def legs(inst: Instrument) -> tuple[str, str | None]:
    """(base, quote) currencies; quote is None for stocks (headlines are about the ticker itself)."""
    if inst.asset_class == "idx_stock":
        return inst.symbol, None
    return inst.symbol[:3], inst.symbol[3:6]


def _has(text: str, words: list[str]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) for w in words)


def _count(text: str, words: list[str]) -> int:
    return sum(1 for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text))


def polarity(text: str) -> float:
    pos, neg = _count(text, POSITIVE), _count(text, NEGATIVE)
    if pos == neg:
        return 0.0
    return (pos - neg) / (pos + neg)


CLAUSE_SPLIT = re.compile(r"\s(?:as|after|amid|while|but|despite|on|ahead of|following)\s|[,;:|]|\s[-–]\s")


def _clause_score(t: str, base: str, quote: str) -> float:
    pol = polarity(t)
    about_base = _has(t, CURRENCY_KEYWORDS.get(base, [base.lower()]))
    about_quote = _has(t, CURRENCY_KEYWORDS.get(quote, [quote.lower()]))
    if about_base and not about_quote:
        return pol
    if about_quote and not about_base:
        return -pol
    return 0.0


def lexicon_score(title: str, inst: Instrument) -> float:
    """Directional score for the instrument from a headline, -1..1.

    Headlines often talk about both legs ("Gold slumps as dollar strength returns"),
    so polarity is attributed clause by clause to the currency each clause mentions.
    """
    t = f" {title.lower()} "
    base, quote = legs(inst)

    if quote is None:  # stock: headline is already about the company
        return polarity(t)

    s = sum(_clause_score(f" {c.strip()} ", base, quote) for c in CLAUSE_SPLIT.split(t) if c and c.strip())
    pair_forms = [f"{base}/{quote}", f"{base}{quote}", f"{base}-{quote}"]
    if s == 0 and _has(t, [p.lower() for p in pair_forms]):
        s = polarity(t)  # "EUR/USD slides below 1.08" -> the pair itself moves
    if _has(t, RISK_OFF):
        s += SAFE_HAVENS.get(base, -0.3) * 0.6 - SAFE_HAVENS.get(quote, -0.3) * 0.6
    return max(-1.0, min(1.0, s))


def is_relevant(title: str, inst: Instrument) -> bool:
    base, quote = legs(inst)
    if quote is None:
        return True
    t = f" {title.lower()} "
    return _has(t, CURRENCY_KEYWORDS.get(base, [base.lower()])) or _has(t, CURRENCY_KEYWORDS.get(quote, [quote.lower()]))


def aggregate(symbol: str, items: list[Headline], sources: list[str]) -> NewsSentiment:
    if not items:
        return NewsSentiment(symbol, 0.0, "no_data", 0, sources, False, [])
    num = den = 0.0
    for h in items:
        w = math.pow(0.5, h.age_hours / HALF_LIFE_HOURS)
        num += h.score * w
        den += w
    score = num / den if den else 0.0
    scored = [h for h in items if h.score != 0]
    label = "bullish" if score >= BULLISH_AT else "bearish" if score <= -BULLISH_AT else "neutral"
    event = any(h.high_impact and h.age_hours <= 3 for h in items)
    items = sorted(items, key=lambda h: h.published, reverse=True)
    return NewsSentiment(symbol, max(-1.0, min(1.0, score)), label, len(scored), sources, event, items)


# --------------------------------------------------------------------------- source parsers
def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_alphavantage(payload: dict, inst: Instrument) -> list[Headline]:
    """Alpha Vantage NEWS_SENTIMENT: uses its per-ticker sentiment for FOREX:<CCY> legs."""
    base, quote = legs(inst)
    want = {f"FOREX:{base}": 1, f"FOREX:{quote}": -1} if quote else {}
    out = []
    for item in payload.get("feed", [])[:MAX_ITEMS]:
        try:
            ts = _iso(datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S"))
        except (KeyError, ValueError):
            continue
        score, used = 0.0, False
        for ts_item in item.get("ticker_sentiment", []):
            sign = want.get(ts_item.get("ticker", ""))
            if sign and float(ts_item.get("relevance_score", 0)) >= 0.1:
                # AV scores are roughly within +-0.35 for "bullish"/"bearish": rescale to +-1
                score += sign * max(-1.0, min(1.0, float(ts_item.get("ticker_sentiment_score", 0)) / 0.35))
                used = True
        title = item.get("title", "").strip()
        if not used:
            if not is_relevant(title, inst):
                continue
            score = lexicon_score(title, inst)
        out.append(Headline(title, item.get("source", "Alpha Vantage"), item.get("url", ""), ts,
                            max(-1.0, min(1.0, score)), "alphavantage" if used else "lexicon"))
    return out


def parse_finnhub(payload: list, inst: Instrument) -> list[Headline]:
    out = []
    for item in (payload or [])[: MAX_ITEMS * 2]:
        title = (item.get("headline") or "").strip()
        if not title or not is_relevant(title, inst):
            continue
        ts = _iso(datetime.fromtimestamp(int(item.get("datetime", 0)), tz=timezone.utc))
        out.append(Headline(title, item.get("source", "Finnhub"), item.get("url", ""), ts, lexicon_score(title, inst)))
    return out


def parse_rss(xml_text: str, inst: Instrument, source: str) -> list[Headline]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title or not is_relevant(title, inst):
            continue
        try:
            ts = _iso(parsedate_to_datetime(item.findtext("pubDate") or ""))
        except (TypeError, ValueError):
            ts = _iso(datetime.now(timezone.utc))
        out.append(Headline(title, source, (item.findtext("link") or "").strip(), ts, lexicon_score(title, inst)))
    return out


def parse_yfinance(news: list, inst: Instrument) -> list[Headline]:
    """yfinance returns either the legacy flat shape or {'content': {...}} (>=0.2.50)."""
    out = []
    for raw in (news or [])[:MAX_ITEMS]:
        c = raw.get("content", raw)
        title = (c.get("title") or "").strip()
        if not title:
            continue
        if "pubDate" in c:
            try:
                ts = _iso(datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00")))
            except ValueError:
                continue
        else:
            ts = _iso(datetime.fromtimestamp(int(c.get("providerPublishTime", 0)), tz=timezone.utc))
        provider = c.get("provider", {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
        url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link", "")
        out.append(Headline(title, provider or "Yahoo Finance", url or "", ts, lexicon_score(title, inst)))
    return out


# --------------------------------------------------------------------------- fetchers
async def _fetch_alphavantage(client: httpx.AsyncClient, inst: Instrument) -> list[Headline]:
    if not settings.alpha_vantage_api_key or inst.asset_class == "idx_stock":
        return []
    base, quote = legs(inst)
    tickers = ",".join(f"FOREX:{c}" for c in (base, quote) if c and c not in {"XAU", "XAG", "BTC"}) or "FOREX:USD"
    r = await client.get("https://www.alphavantage.co/query", params={
        "function": "NEWS_SENTIMENT", "tickers": tickers, "limit": 50, "sort": "LATEST",
        "apikey": settings.alpha_vantage_api_key,
    })
    data = r.json()
    if "feed" not in data:  # rate limit / error message
        log.warning("Alpha Vantage: %s", data.get("Information") or data.get("Note") or data)
        return []
    return parse_alphavantage(data, inst)


async def _fetch_finnhub(client: httpx.AsyncClient, inst: Instrument) -> list[Headline]:
    if not settings.finnhub_api_key or inst.asset_class == "idx_stock":
        return []
    r = await client.get("https://finnhub.io/api/v1/news", params={"category": "forex", "token": settings.finnhub_api_key})
    r.raise_for_status()
    return parse_finnhub(r.json(), inst)


async def _fetch_rss(client: httpx.AsyncClient, inst: Instrument) -> list[Headline]:
    if inst.asset_class == "idx_stock":
        return []
    out: list[Headline] = []
    for url in settings.news_rss_feeds:
        try:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (AI Virtual Office)"})
            r.raise_for_status()
            out += parse_rss(r.text, inst, httpx.URL(url).host)
        except Exception as exc:
            log.warning("RSS %s failed: %s", url, exc)
    return out


async def _fetch_yfinance(inst: Instrument) -> list[Headline]:
    if inst.asset_class != "idx_stock":
        return []
    try:
        import yfinance as yf
    except ImportError:
        return []
    news = await asyncio.to_thread(lambda: yf.Ticker(inst.yf_ticker).news)
    return parse_yfinance(news, inst)


def _dedupe(items: list[Headline], lookback_h: float) -> list[Headline]:
    seen, out = set(), []
    for h in items:
        key = re.sub(r"\W+", " ", h.title.lower()).strip()[:80]
        if key in seen or h.age_hours > lookback_h:
            continue
        seen.add(key)
        h.high_impact = _has(f" {h.title.lower()} ", HIGH_IMPACT)
        out.append(h)
    return out


LLM_SYSTEM = (
    "Kamu analis sentimen berita forex/saham. Untuk instrumen yang diberikan, beri skor tiap judul berita dari -1 "
    "(sangat bearish untuk harga instrumen) sampai +1 (sangat bullish); 0 jika tidak relevan. Ingat: untuk pair BASE/QUOTE, "
    "berita positif untuk QUOTE berarti bearish untuk pair. Balas HANYA JSON: {\"scores\": [angka, ...]} sesuai urutan."
)


async def _llm_rescore(inst: Instrument, items: list[Headline]) -> None:
    """Let the debate model rescore lexicon-only headlines (bounded to -1..1, best-effort)."""
    targets = [h for h in items if h.method == "lexicon"][:20]
    if not targets or not settings.llm_enabled or not settings.news_use_llm:
        return
    base, quote = legs(inst)
    listing = "\n".join(f"{i + 1}. {h.title}" for i, h in enumerate(targets))
    reply = extract_json(await chat(
        settings.model_debate, LLM_SYSTEM,
        f"INSTRUMEN: {inst.symbol} (base {base}, quote {quote or '-'})\nJUDUL:\n{listing}", temperature=0.0,
    ))
    scores = reply.get("scores") if isinstance(reply, dict) else None
    if not isinstance(scores, list) or len(scores) != len(targets):
        return
    for h, s in zip(targets, scores):
        try:
            h.score, h.method = max(-1.0, min(1.0, float(s))), "llm"
        except (TypeError, ValueError):
            continue


async def load_news(inst: Instrument) -> NewsSentiment:
    """Never raises: a failing source is skipped, no data -> label 'no_data'."""
    lookback = settings.news_lookback_hours
    items: list[Headline] = []
    sources: list[str] = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        jobs = {
            "alphavantage": _fetch_alphavantage(client, inst),
            "finnhub": _fetch_finnhub(client, inst),
            "rss": _fetch_rss(client, inst),
            "yfinance": _fetch_yfinance(inst),
        }
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    for name, res in zip(jobs, results):
        if isinstance(res, Exception):
            log.warning("news source %s failed: %s", name, res)
        elif res:
            sources.append(name)
            items += res
    items = _dedupe(sorted(items, key=lambda h: h.published, reverse=True), lookback)[:MAX_ITEMS]
    try:
        await _llm_rescore(inst, items)
    except Exception as exc:
        log.warning("LLM news scoring failed: %s", exc)
    return aggregate(inst.symbol, items, sources)
