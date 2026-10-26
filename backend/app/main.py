"""FastAPI + Socket.IO bridge between the agents and the 3D office.

Run:  uvicorn app.main:asgi --reload --port 8000   (from the backend/ folder)
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agents.it_department import ROLES, run_it_pipeline
from .agents.trading import run_debate
from .config import settings
from .db import Store
from .market.data import INTERVALS, load_market
from .market.indicators import candles_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("office")

store = Store()
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.cors_origins)
app = FastAPI(title="AI Virtual Office & Trading Hub", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

AGENTS = {**ROLES, "bull": "Bull Agent", "bear": "Bear Agent", "risk": "Risk Agent"}
_running: set[str] = set()  # one job per department at a time


class TradeRequest(BaseModel):
    symbol: str = Field(min_length=2, max_length=15, pattern=r"^[A-Za-z0-9./=\-]+$")
    interval: str = "15m"
    capital: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0, le=10)
    today_loss_pct: float = Field(default=0.0, ge=0)
    account_currency: str = Field(default="IDR", pattern=r"^(IDR|USD)$")


class ItRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)


def _emitter(session_id: str):
    async def emit(event: str, data: dict) -> None:
        payload = {**data, "session_id": session_id}
        if event == "agent:message":
            store.add_message(session_id, data["agent"], data.get("kind", "text"), data.get("text", ""))
            if data.get("data") is not None:
                store.add_message(session_id, data["agent"], f"{data.get('kind', 'text')}:data", data["data"])
        await sio.emit(event, payload)
        await asyncio.sleep(0.6)  # pace the stream so avatars visibly take turns
    return emit


async def _trade_job(req: TradeRequest, session_id: str) -> dict:
    emit = _emitter(session_id)
    await sio.emit("job:start", {"session_id": session_id, "dept": "trade", "input": req.symbol})
    try:
        md = await load_market(req.symbol, req.interval)
        await sio.emit("trade:market", {
            "session_id": session_id, "symbol": md.instrument.symbol, "source": md.source,
            "interval": md.interval, "candles": candles_payload(md.candles),
        })
        plan = await run_debate(
            md, emit, capital=req.capital, risk_pct=req.risk_pct,
            today_loss_pct=req.today_loss_pct, account_currency=req.account_currency,
        )
        plan["session_id"] = session_id
        store.save_plan(session_id, plan)
        await sio.emit("trade:plan", plan)
        return plan
    except Exception as exc:
        log.exception("trade job failed")
        await sio.emit("job:error", {"session_id": session_id, "dept": "trade", "error": str(exc)})
        raise
    finally:
        _running.discard("trade")
        await sio.emit("job:end", {"session_id": session_id, "dept": "trade"})


async def _it_job(req: ItRequest, session_id: str) -> dict:
    emit = _emitter(session_id)
    await sio.emit("job:start", {"session_id": session_id, "dept": "it", "input": req.prompt})
    try:
        state = await run_it_pipeline(req.prompt, emit)
        await sio.emit("it:result", {"session_id": session_id, **state})
        return state
    except Exception as exc:
        log.exception("it job failed")
        await sio.emit("job:error", {"session_id": session_id, "dept": "it", "error": str(exc)})
        raise
    finally:
        _running.discard("it")
        await sio.emit("job:end", {"session_id": session_id, "dept": "it"})


def _claim(dept: str) -> str:
    if dept in _running:
        raise HTTPException(409, f"Departemen {dept} masih bekerja, tunggu selesai")
    _running.add(dept)
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- REST
@app.get("/api/health")
def health():
    return {"ok": True, "llm_enabled": settings.llm_enabled, "busy": sorted(_running)}


@app.get("/api/agents")
def agents():
    return [{"id": k, "name": v} for k, v in AGENTS.items()]


@app.post("/api/trade/analyze", status_code=202)
async def trade_analyze(req: TradeRequest):
    if req.interval not in INTERVALS:
        raise HTTPException(422, f"interval harus salah satu dari {list(INTERVALS)}")
    sid = _claim("trade")
    store.create_session(sid, "trade", req.model_dump_json())
    asyncio.create_task(_trade_job(req, sid))
    return {"session_id": sid}


@app.post("/api/it/request", status_code=202)
async def it_request(req: ItRequest):
    sid = _claim("it")
    store.create_session(sid, "it", req.prompt)
    asyncio.create_task(_it_job(req, sid))
    return {"session_id": sid}


@app.get("/api/sessions")
def sessions(limit: int = 20):
    return store.recent_sessions(min(limit, 100))


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    return store.session_messages(session_id)


@app.get("/api/plans")
def plans(symbol: str | None = None):
    return store.recent_plans(symbol.upper() if symbol else None)


# --------------------------------------------------------------------------- Socket.IO
@sio.event
async def connect(sid, environ):
    await sio.emit("hello", {"agents": agents(), "llm_enabled": settings.llm_enabled, "busy": sorted(_running)}, to=sid)


@sio.on("trade:analyze")
async def ws_trade(sid, data):
    try:
        res = await trade_analyze(TradeRequest(**(data or {})))
        return {"ok": True, **res}
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    except Exception as e:  # pydantic validation
        return {"ok": False, "error": str(e)}


@sio.on("it:request")
async def ws_it(sid, data):
    try:
        res = await it_request(ItRequest(**(data or {})))
        return {"ok": True, **res}
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    except Exception as e:
        return {"ok": False, "error": str(e)}


asgi = socketio.ASGIApp(sio, other_asgi_app=app)
