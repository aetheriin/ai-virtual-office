import pandas as pd
import pytest

from app.market import data as data_mod
from app.market.data import InsufficientData, SymbolNotFound, load_many_sync, mt5_symbol_name, synthetic_candles

BROKER = ["EURUSD", "XAUUSDm", "XAUUSD.r", "XAUUSD-ECN", "XAUUSDX_MINI_CONTRACT", "GBPUSD.pro", "USDJPY#"]


@pytest.mark.parametrize("wanted,mapping,suffix,expected", [
    ("EURUSD", "", "", "EURUSD"),                       # exact
    ("XAUUSD", "", "", "XAUUSDm"),                      # shortest broker variant
    ("XAUUSD", '{"XAUUSD": "XAUUSD-ECN"}', "", "XAUUSD-ECN"),  # explicit map wins
    ("XAUUSD", "", ".r", "XAUUSD.r"),                   # configured suffix
    ("GBPUSD", "", "", "GBPUSD.pro"),
    ("USDJPY", "", "", "USDJPY#"),
    ("AUDUSD", "", "", None),                           # broker doesn't offer it
    ("XAUUSD", "not json", "", "XAUUSDm"),              # bad map is ignored
])
def test_mt5_symbol_name(wanted, mapping, suffix, expected):
    assert mt5_symbol_name(wanted, BROKER, mapping, suffix) == expected


@pytest.fixture
def no_sources(monkeypatch, patch_settings):
    patch_settings(allow_synthetic_data=False)
    for name in ("_from_mt5", "_from_yfinance", "_from_twelvedata"):
        monkeypatch.setattr(data_mod, name, lambda inst, interval: None)
    monkeypatch.setattr(data_mod, "_download_many", lambda insts, interval: {})


def test_unknown_ticker_raises_clear_error(no_sources):
    with pytest.raises(SymbolNotFound, match="BUAV.*tidak ditemukan.*BUAV.JK"):
        data_mod._load_sync("BUAV", "15m")


def test_too_few_candles_is_reported(no_sources, monkeypatch):
    monkeypatch.setattr(data_mod, "_from_yfinance", lambda inst, interval: synthetic_candles("x", n=12))
    with pytest.raises(InsufficientData, match="hanya 12 candle"):
        data_mod._load_sync("BUVA", "5m")


def test_synthetic_only_when_enabled(no_sources, patch_settings):
    patch_settings(allow_synthetic_data=True)
    assert data_mod._load_sync("BUAV", "15m").source == "synthetic"


def test_load_many_uses_batch_then_fallback(no_sources, monkeypatch):
    monkeypatch.setattr(data_mod, "_download_many", lambda insts, interval: {"BBCA": synthetic_candles("a"), "BUMI": synthetic_candles("b", n=10)})
    monkeypatch.setattr(data_mod, "_from_yfinance",
                        lambda inst, interval: synthetic_candles("c") if inst.symbol == "TLKM" else None)
    got, errors = load_many_sync(["bbca", "BUMI", "TLKM", "XXXX"], "15m")
    assert set(got) == {"BBCA", "TLKM"}
    assert got["BBCA"].source == "yfinance"
    assert set(errors) == {"BUMI", "XXXX"} and "tidak ditemukan" in errors["XXXX"]
    assert "hanya 10 candle" in errors["BUMI"]
