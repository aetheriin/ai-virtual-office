"""Candlestick data sources: yfinance -> Twelve Data -> MetaTrader5 -> synthetic (demo only).

Returned DataFrame columns: open, high, low, close, volume (DatetimeIndex, oldest first).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass

import httpx
import numpy as np
import pandas as pd

from ..config import settings

log = logging.getLogger(__name__)

# Friendly symbol -> (yfinance ticker, Twelve Data symbol, asset class)
FOREX_MAP = {
    "XAUUSD": ("GC=F", "XAU/USD", "gold"),
    "XAGUSD": ("SI=F", "XAG/USD", "metal"),
    "EURUSD": ("EURUSD=X", "EUR/USD", "forex"),
    "GBPUSD": ("GBPUSD=X", "GBP/USD", "forex"),
    "USDJPY": ("JPY=X", "USD/JPY", "forex"),
    "AUDUSD": ("AUDUSD=X", "AUD/USD", "forex"),
    "USDIDR": ("IDR=X", "USD/IDR", "forex"),
    "BTCUSD": ("BTC-USD", "BTC/USD", "crypto"),
}

INTERVALS = {  # interval -> (yfinance period, twelve data interval)
    "5m": ("5d", "5min"),
    "15m": ("5d", "15min"),
    "30m": ("1mo", "30min"),
    "1h": ("1mo", "1h"),
    "1d": ("1y", "1day"),
}


MIN_CANDLES = 30


class SymbolNotFound(LookupError):
    """No source knows this ticker (typo, delisted, or not on Yahoo/Twelve Data/MT5)."""


class InsufficientData(LookupError):
    """The ticker exists but has too few candles for this timeframe (illiquid stock, new listing)."""


@dataclass
class Instrument:
    symbol: str          # what the user typed, normalised (BBCA, XAUUSD)
    yf_ticker: str
    td_symbol: str
    asset_class: str     # idx_stock | forex | gold | metal | crypto

    @property
    def currency(self) -> str:
        return "IDR" if self.asset_class == "idx_stock" else "USD"


def resolve(symbol: str) -> Instrument:
    s = symbol.strip().upper().replace("/", "")
    if s in FOREX_MAP:
        yf_t, td, cls = FOREX_MAP[s]
        return Instrument(s, yf_t, td, cls)
    if s.endswith(".JK"):
        s = s[:-3]
    # Anything else is treated as an IDX ticker (BBCA -> BBCA.JK)
    return Instrument(s, f"{s}.JK", f"{s}:IDX", "idx_stock")


@dataclass
class MarketData:
    instrument: Instrument
    interval: str
    candles: pd.DataFrame
    source: str  # yfinance | twelvedata | mt5 | synthetic

    @property
    def is_live(self) -> bool:
        return self.source != "synthetic"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].astype(float)
    return df.dropna().sort_index()


def _from_yfinance(inst: Instrument, interval: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    period = INTERVALS[interval][0]
    df = yf.Ticker(inst.yf_ticker).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return None
    return _clean(df)


def _from_twelvedata(inst: Instrument, interval: str) -> pd.DataFrame | None:
    if not settings.twelve_data_api_key:
        return None
    r = httpx.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": inst.td_symbol,
            "interval": INTERVALS[interval][1],
            "outputsize": 300,
            "apikey": settings.twelve_data_api_key,
        },
        timeout=20,
    )
    data = r.json()
    if data.get("status") != "ok":
        return None
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    if "volume" not in df:
        df["volume"] = 0
    return _clean(df)


def mt5_symbol_name(wanted: str, available: list[str], mapping: str = "", suffix: str = "") -> str | None:
    """Find the broker's name for a symbol: explicit map > suffix > exact > 'XAUUSD' + broker suffix.

    Brokers append suffixes such as XAUUSDm, XAUUSD.r, XAUUSD-ECN, XAUUSD_i; when several match,
    the shortest wins (usually the standard account).
    """
    names = set(available)
    try:
        explicit = json.loads(mapping).get(wanted) if mapping else None
    except (ValueError, AttributeError):
        explicit = None
    for candidate in (explicit, wanted + suffix if suffix else None, wanted):
        if candidate and candidate in names:
            return candidate
    pattern = re.compile(rf"^{re.escape(wanted)}[._\-#]?[A-Za-z0-9]{{0,6}}$", re.I)
    matches = sorted((n for n in names if pattern.match(n)), key=lambda n: (len(n), n))
    return matches[0] if matches else None


def _from_mt5(inst: Instrument, interval: str) -> pd.DataFrame | None:
    """MetaTrader5 only works on Windows with a running terminal; skipped elsewhere."""
    if inst.asset_class == "idx_stock":
        return None  # IDX stocks come from Yahoo; MT5 brokers here are forex/CFD
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    tf = {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
          "1h": mt5.TIMEFRAME_H1, "1d": mt5.TIMEFRAME_D1}[interval]
    if not mt5.initialize():
        return None
    try:
        name = mt5_symbol_name(inst.symbol, [s.name for s in (mt5.symbols_get() or [])],
                               settings.mt5_symbol_map, settings.mt5_symbol_suffix)
        if not name:
            log.warning("MT5: no broker symbol for %s (set MT5_SYMBOL_MAP)", inst.symbol)
            return None
        mt5.symbol_select(name, True)  # make sure the terminal streams it
        rates = mt5.copy_rates_from_pos(name, tf, 0, 300)
    finally:
        mt5.shutdown()
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})
    return _clean(df)


def synthetic_candles(seed_text: str, n: int = 200, start_price: float | None = None) -> pd.DataFrame:
    """Deterministic random walk so demos are reproducible. NEVER trade on this."""
    rng = np.random.default_rng(int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16))
    price = start_price or float(rng.uniform(1_000, 10_000))
    drift = rng.normal(0, 0.0006)
    closes, opens, highs, lows, vols = [], [], [], [], []
    for _ in range(n):
        o = price
        c = o * (1 + drift + rng.normal(0, 0.004))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.0025)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.0025)))
        opens.append(o); closes.append(c); highs.append(h); lows.append(lo)
        vols.append(float(rng.integers(50_000, 500_000)))
        price = c
    idx = pd.date_range(end=pd.Timestamp.now("UTC").floor("15min"), periods=n, freq="15min")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx)


def _synthetic(inst: Instrument, interval: str) -> MarketData:
    start = {"forex": 1.1, "gold": 2400.0, "metal": 30.0, "crypto": 60_000.0}.get(inst.asset_class)
    return MarketData(inst, interval, synthetic_candles(inst.symbol + interval, start_price=start), "synthetic")


def _not_found(inst: Instrument, interval: str, best: int) -> LookupError:
    if best:
        return InsufficientData(
            f"{inst.symbol}: hanya {best} candle di timeframe {interval} (butuh {MIN_CANDLES}). "
            "Saham kurang likuid atau baru listing; coba timeframe 1h/1d."
        )
    where = "Yahoo Finance (" + inst.yf_ticker + ")" + (", Twelve Data" if settings.twelve_data_api_key else "")
    return SymbolNotFound(f"Kode '{inst.symbol}' tidak ditemukan di {where}. Cek ejaan kodenya.")


def _load_sync(symbol: str, interval: str) -> MarketData:
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval {interval!r}; choose one of {list(INTERVALS)}")
    inst = resolve(symbol)
    best = 0
    for name, loader in (("mt5", _from_mt5), ("yfinance", _from_yfinance), ("twelvedata", _from_twelvedata)):
        try:
            df = loader(inst, interval)
        except Exception as exc:
            log.warning("%s failed for %s: %s", name, inst.symbol, exc)
            df = None
        if df is not None:
            best = max(best, len(df))
            if len(df) >= MIN_CANDLES:
                return MarketData(inst, interval, df.tail(300), name)
    if settings.allow_synthetic_data:
        return _synthetic(inst, interval)
    raise _not_found(inst, interval, best)


def _download_many(insts: list[Instrument], interval: str) -> dict[str, pd.DataFrame]:
    """One yfinance request for many tickers (screener); missing tickers are simply absent."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    tickers = [i.yf_ticker for i in insts]
    raw = yf.download(tickers, period=INTERVALS[interval][0], interval=interval, group_by="ticker",
                      auto_adjust=False, threads=True, progress=False)
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    for inst in insts:
        try:
            part = raw[inst.yf_ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            part = _clean(part)
        except (KeyError, ValueError):
            continue
        if len(part):
            out[inst.symbol] = part
    return out


def load_many_sync(symbols: list[str], interval: str) -> tuple[dict[str, MarketData], dict[str, str]]:
    """(data per symbol, error per symbol). Batch download first, per-symbol fallback for the rest."""
    insts = {resolve(s).symbol: resolve(s) for s in symbols}
    data: dict[str, MarketData] = {}
    errors: dict[str, str] = {}
    try:
        batch = _download_many(list(insts.values()), interval)
    except Exception as exc:
        log.warning("batch download failed: %s", exc)
        batch = {}
    for sym, inst in insts.items():
        df = batch.get(sym)
        if df is not None and len(df) >= MIN_CANDLES:
            data[sym] = MarketData(inst, interval, df.tail(300), "yfinance")
            continue
        try:
            data[sym] = _load_sync(sym, interval)
        except LookupError as exc:
            errors[sym] = str(_not_found(inst, interval, len(df)) if df is not None and len(df) else exc)
    return data, errors


async def load_market(symbol: str, interval: str = "15m") -> MarketData:
    return await asyncio.to_thread(_load_sync, symbol, interval)
