"""Stock screener: scan a universe of IDX stocks and rank BUY candidates.

Every stock goes through exactly the same deterministic pipeline as a single analysis
(facts -> Bull/Bear evidence -> ARA cap -> Risk Agent hard rules), without LLM calls so a
scan of ~50 stocks stays fast and free. Only plans that survive every veto become
recommendations; bullish ones that were vetoed (RR, ARA, liquidity...) are listed as "pantau".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .agents.trading import MarketContext, bear_case, bull_case, cap_to_limits, fmt, judge
from .config import settings
from .market.data import MarketData, load_many_sync
from .market.indicators import compute_facts

log = logging.getLogger(__name__)

# Example universe of large, frequently traded IDX stocks. NOT an official index list (LQ45/IDX80
# constituents change every review); edit it from the UI or PUT /api/screener/universe.
DEFAULT_UNIVERSE = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "TLKM", "ISAT", "EXCL", "TOWR", "ASII", "UNTR", "UNVR", "ICBP", "INDF",
    "MYOR", "KLBF", "SIDO", "CPIN", "JPFA", "AMRT", "MAPI", "ACES", "ERAA", "ADRO", "PTBA", "ITMG", "HRUM", "BUMI",
    "ANTM", "INCO", "MDKA", "TINS", "MBMA", "NCKL", "AMMN", "PGAS", "MEDC", "AKRA", "BRPT", "TPIA", "INKP", "SMGR",
    "INTP", "JSMR", "BSDE", "CTRA", "PWON", "SMRA", "GOTO", "BUKA", "EMTK", "ARTO",
]
MAX_UNIVERSE = 120

Progress = Callable[[dict], Awaitable[None]]


def _score(plan: dict, liq_level: str | None) -> float:
    """Ranking: evidence gap first, then reward potential, small bonus for good liquidity."""
    gap = plan["scores"]["bull"] - plan["scores"]["bear"]
    return round(gap + 0.5 * min(plan["rr_tp2"], 3) + (0.5 if liq_level == "ok" else 0), 2)


def analyse_stock(md: MarketData, *, capital: float, risk_pct: float, account_currency: str = "IDR") -> dict:
    inst = md.instrument
    f = compute_facts(md.candles)
    ctx = MarketContext.from_market(md)
    bull = cap_to_limits(bull_case(f, inst.asset_class), ctx.limits, inst.asset_class)
    bear = bear_case(f, inst.asset_class, bull)
    plan = judge(f, bull, bear, capital=capital, risk_pct=risk_pct, today_loss_pct=0, asset=inst.asset_class,
                 quote_ccy=inst.currency, account_ccy=account_currency, ctx=ctx)
    liq = ctx.liq.level if ctx.liq else None
    return {
        "symbol": inst.symbol, "asset_class": inst.asset_class, "interval": md.interval, "price": f.last_close,
        "as_of": f.last_time, "data_source": md.source, "demo": not md.is_live,
        "status": plan["status"], "bias": plan["bias"],
        "entry": plan["entry"], "stop_loss": plan["stop_loss"], "tp1": plan["tp1"], "tp2": plan["tp2"],
        "rr_tp1": plan["rr_tp1"], "rr_tp2": plan["rr_tp2"], "position": plan["position"],
        "scores": plan["scores"], "score": _score(plan, liq), "liquidity": liq,
        "evidence": bull.evidence[:4], "reasons": plan["reasons"], "warnings": plan["warnings"],
        "limits": plan["limits"], "structure": f.structure, "trigger": plan["trigger"],
        "summary": (f"Beli di sekitar {fmt(plan['entry'])}, SL {fmt(plan['stop_loss'])}, "
                    f"TP1 {fmt(plan['tp1'])} / TP2 {fmt(plan['tp2'])} (RR 1:{plan['rr_tp2']})"),
    }


async def run_screener(
    symbols: list[str], interval: str, *, capital: float, risk_pct: float, run_id: str,
    progress: Progress | None = None, top: int = 10,
) -> dict:
    symbols = list(dict.fromkeys(s.upper() for s in symbols))[:MAX_UNIVERSE]
    if progress:
        await progress({"stage": "download", "done": 0, "total": len(symbols)})
    data, errors = await asyncio.to_thread(load_many_sync, symbols, interval)

    rows: list[dict] = []
    for i, (sym, md) in enumerate(data.items(), 1):
        if not md.is_live and not settings.allow_synthetic_data:
            continue
        try:
            rows.append(analyse_stock(md, capital=capital, risk_pct=risk_pct))
        except Exception as exc:  # one bad series must not kill the scan
            errors[sym] = f"analisa gagal: {exc}"
        if progress and (i % 5 == 0 or i == len(data)):
            await progress({"stage": "analyse", "done": i, "total": len(data)})
        await asyncio.sleep(0)

    buys = sorted((r for r in rows if r["status"] == "BUY"), key=lambda r: r["score"], reverse=True)
    watch = sorted((r for r in rows if r["status"] == "WAIT" and r["bias"] == "LONG"
                    and r["scores"]["bull"] - r["scores"]["bear"] >= 2), key=lambda r: r["score"], reverse=True)
    avoid = [r["symbol"] for r in rows if r["bias"] == "SHORT" and r["scores"]["bear"] - r["scores"]["bull"] >= 2]
    return {
        "id": run_id,
        "interval": interval,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe": len(symbols),
        "scanned": len(rows),
        "errors": errors,
        "recommendations": buys[:top],
        "watch": watch[:top],
        "avoid": avoid,
        "demo": any(r["demo"] for r in rows),
        "disclaimer": ("Hasil pemindaian teknikal otomatis, bukan saran investasi. Verifikasi sendiri, "
                       "dan pantau hasilnya di Jurnal sebelum memakai uang sungguhan."),
    }
