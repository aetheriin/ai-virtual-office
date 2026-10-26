"""Journal service: record plans as paper trades and re-evaluate open ones against fresh candles."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .db import Store
from .journal import evaluate
from .market.data import MarketData

log = logging.getLogger(__name__)

Loader = Callable[[str, str], Awaitable[MarketData]]


def record_plan(store: Store, plan: dict, *, source: str = "analisa", session_id: str | None = None) -> int | None:
    """Only actionable plans on live data are journaled (WAIT and demo/synthetic plans are skipped)."""
    if plan.get("status") not in {"BUY", "SELL"} or plan.get("demo"):
        return None
    pos = plan.get("position") or {}
    return store.add_paper_trade({
        "session_id": session_id or plan.get("session_id"),
        "source": source,
        "symbol": plan["symbol"],
        "asset_class": plan.get("asset_class", ""),
        "interval": plan.get("interval", "15m"),
        "side": "LONG" if plan["status"] == "BUY" else "SHORT",
        "entry": plan["entry"], "stop_loss": plan["stop_loss"], "tp1": plan["tp1"], "tp2": plan["tp2"],
        "quantity": pos.get("quantity"), "unit": pos.get("unit"), "risk_amount": pos.get("max_loss") or pos.get("risk_amount"),
        "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


async def refresh(store: Store, load: Loader) -> dict:
    """Evaluate every open trade; one data request per (symbol, interval)."""
    active = store.paper_trades("active", limit=1000)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in active:
        groups[(t["symbol"], t["interval"])].append(t)
    checked = closed = 0
    errors: dict[str, str] = {}
    now = datetime.now(timezone.utc)
    for (symbol, interval), trades in groups.items():
        try:
            md = await load(symbol, interval)
        except Exception as exc:  # keep going for the other symbols
            errors[symbol] = str(exc)
            continue
        if not md.is_live:
            continue  # never score real plans against invented candles
        for t in trades:
            out = evaluate(t, md.candles, now)
            store.update_paper_trade(t["id"], status=out.status, tp1_hit=int(out.tp1_hit), result=out.result,
                                     r_multiple=out.r_multiple, exit_price=out.exit_price, closed_at=out.closed_at,
                                     last_checked_at=now.isoformat(timespec="seconds"))
            checked += 1
            closed += out.status == "closed"
    return {"checked": checked, "closed": closed, "errors": errors}
