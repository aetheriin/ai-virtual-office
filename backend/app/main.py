"""FastAPI + Socket.IO bridge between the agents and the 3D office.

Run:  uvicorn app.main:asgi --reload --port 8000   (from the backend/ folder)
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agents.it_department import ROLES, run_it_pipeline
from .agents.trading import run_debate
from .config import settings
from .db import Store
from .market.data import INTERVALS, load_market, resolve
from .market.indicators import candles_payload
from .market.news import empty as empty_news, load_news
from .github.client import GitHubClient, GitHubError
from .github.pr import RepoContext, load_repo_context, open_sprint_pr, read_existing, valid_repo_name
from .projects.store import DEFAULT_PROJECT, ProjectExists, ProjectStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("office")

store = Store()
projects = ProjectStore()
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.cors_origins)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await projects.init(migrate=settings.db_auto_migrate)
    log.info("project database: %s", projects.backend)
    yield
    await projects.close()


app = FastAPI(title="AI Virtual Office & Trading Hub", version="0.2.0", lifespan=lifespan)
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
    project_id: int | None = Field(default=None, gt=0)


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=120, pattern=r"\S")
    description: str = Field(default="", max_length=4000)
    repo: str | None = Field(default=None, max_length=200, description="GitHub repo owner/name")
    base_branch: str | None = Field(default=None, max_length=100, pattern=r"^[\w./-]+$")


class ProjectPatch(BaseModel):
    description: str | None = Field(default=None, max_length=4000)
    repo: str | None = Field(default=None, max_length=200, description="'' to disconnect")
    base_branch: str | None = Field(default=None, max_length=100, pattern=r"^[\w./-]*$")


async def _check_repo(repo: str) -> dict:
    """Validate 'owner/name' and, when a token is configured, that it can push there."""
    if not valid_repo_name(repo):
        raise HTTPException(422, "Format repo harus owner/nama, mis. aetheriin/toko-online")
    if not settings.github_token:
        return {"checked": False, "warning": "GITHUB_TOKEN belum diatur; PR baru bisa dibuat setelah token diisi"}
    async with GitHubClient() as gh:
        try:
            info = await gh.repo(repo)
        except GitHubError as e:
            if e.status in (401, 403, 404):
                raise HTTPException(422, f"Token tidak bisa mengakses {repo} (GitHub {e.status}). "
                                         "Tambahkan repo ini ke fine-grained token Anda.")
            raise HTTPException(502, f"GitHub error: {e.message}")
    if not info.can_push:
        raise HTTPException(422, f"Token hanya punya akses baca ke {repo}; butuh izin Contents & Pull requests: write")
    return {"checked": True, "default_branch": info.default_branch, "private": info.private}


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
        news = await load_news(md.instrument) if settings.enable_news else empty_news(md.instrument.symbol)
        await sio.emit("trade:news", {"session_id": session_id, **news.to_dict()})
        plan = await run_debate(
            md, emit, capital=req.capital, risk_pct=req.risk_pct,
            today_loss_pct=req.today_loss_pct, account_currency=req.account_currency, news=news,
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


async def _project_context(project_id: int) -> str:
    """Earlier sprints + open high QA findings, so the PM plans on top of what already exists."""
    runs = [r for r in await projects.list_runs(project_id, limit=5) if r["status"] == "done"]
    findings = await projects.open_findings(project_id)
    lines = [f"- Sprint sebelumnya: {r['prompt'][:160]} (QA: {r['review_verdict'] or '-'})" for r in runs]
    lines += [f"- Temuan QA HIGH belum ditutup ({f['agent']}): {f['issue'][:200]}" for f in findings[:5]]
    return "\n".join(lines)


class _RepoAccess:
    """Adapter handed to the IT pipeline: repo brief + reading files the agents plan to change."""

    def __init__(self, gh: GitHubClient, ctx: RepoContext):
        self.gh, self.ctx, self.brief = gh, ctx, ctx.brief

    async def read(self, paths: list[str]) -> dict[str, str]:
        try:
            return await read_existing(self.gh, self.ctx, paths)
        except GitHubError as e:
            log.warning("reading repo files failed: %s", e)
            return {}


async def _open_pr(gh: GitHubClient, ctx: RepoContext, state: dict, session_id: str, project_name: str, emit) -> None:
    if not settings.llm_enabled and not settings.allow_template_pr:
        reason = "Rule engine aktif (tanpa LLM): kode template tidak dikirim ke repo. Set ALLOW_TEMPLATE_PR=true untuk uji coba."
        await projects.set_pr(session_id, "skipped", error=reason)
        await sio.emit("it:pr", {"session_id": session_id, "status": "skipped", "error": reason})
        return
    await emit("agent:status", {"agent": "pm", "state": "standing"})
    await emit("agent:message", {"agent": "pm", "kind": "pr", "text": f"Membuka pull request ke {ctx.repo}..."})
    try:
        res = await open_sprint_pr(gh, ctx, state, session_id, project_name)
    except (GitHubError, httpx.HTTPError) as e:
        log.warning("PR failed: %s", e)
        res = None
        msg = e.message if isinstance(e, GitHubError) else f"koneksi ke GitHub gagal ({type(e).__name__})"
        await projects.set_pr(session_id, "failed", error=msg)
        await sio.emit("it:pr", {"session_id": session_id, "status": "failed", "error": msg})
        await emit("agent:message", {"agent": "pm", "kind": "pr", "text": f"Gagal membuka PR: {msg}"})
    if res:
        await projects.set_pr(session_id, res.status, url=res.url, number=res.number, branch=res.branch, error=res.error)
        await sio.emit("it:pr", {"session_id": session_id, "status": res.status, "url": res.url,
                                 "number": res.number, "branch": res.branch, "error": res.error})
        text = (f"PR #{res.number} dibuka{' (draft)' if res.status == 'draft' else ''}: {res.files} file. Silakan review di GitHub."
                if res.url else f"PR tidak dibuat: {res.error}")
        await emit("agent:message", {"agent": "pm", "kind": "pr", "text": text, "data": {"url": res.url}})
    await emit("agent:status", {"agent": "pm", "state": "idle"})


async def _it_job(req: ItRequest, session_id: str, project_id: int) -> dict:
    base_emit = _emitter(session_id)

    async def emit(event: str, data: dict) -> None:
        # Persist task board changes to PostgreSQL while streaming them to the office
        if event == "it:tasks":
            await projects.set_tasks(session_id, data["tasks"])
        elif event == "it:task_status":
            await projects.set_task_status(session_id, data["assignee"], data["status"])
        await base_emit(event, data)

    await sio.emit("job:start", {"session_id": session_id, "dept": "it", "input": req.prompt, "project_id": project_id})
    try:
        async with AsyncExitStack() as stack:
            project = await projects.get_project(project_id)
            gh, ctx = await _connect_repo(stack, project, session_id, emit)
            repo = _RepoAccess(gh, ctx) if gh and ctx else None
            state = await run_it_pipeline(req.prompt, emit, await _project_context(project_id), repo)
            await projects.finish_run(session_id, state)
            await sio.emit("it:result", {"session_id": session_id, "project_id": project_id, **state})
            if gh and ctx:
                await _open_pr(gh, ctx, state, session_id, project.name, emit)
            return state
    except Exception as exc:
        log.exception("it job failed")
        await projects.fail_run(session_id, str(exc))
        await sio.emit("job:error", {"session_id": session_id, "dept": "it", "error": str(exc)})
        raise
    finally:
        _running.discard("it")
        await sio.emit("job:end", {"session_id": session_id, "dept": "it"})


async def _connect_repo(stack: AsyncExitStack, project, session_id: str, emit) -> tuple[GitHubClient | None, RepoContext | None]:
    """Open a GitHub client and read the project's repo; on any problem the sprint continues without a PR."""
    if not (project and project.repo_full_name and settings.auto_pr):
        return None, None
    if not settings.github_token:
        await projects.set_pr(session_id, "skipped", error="GITHUB_TOKEN belum diatur")
        return None, None
    gh = await stack.enter_async_context(GitHubClient())
    try:
        ctx = await load_repo_context(gh, project.repo_full_name, project.base_branch)
        await projects.set_pr(session_id, "pending")  # a PR will follow this sprint
        await sio.emit("it:pr", {"session_id": session_id, "status": "pending", "repo": ctx.repo, "empty": ctx.empty})
        return gh, ctx
    except (GitHubError, httpx.HTTPError) as e:
        msg = e.message if isinstance(e, GitHubError) else f"koneksi ke GitHub gagal ({type(e).__name__})"
        await projects.set_pr(session_id, "failed", error=f"Tidak bisa membaca repo: {msg}")
        await emit("agent:message", {"agent": "pm", "kind": "pr",
                                     "text": f"Repo {project.repo_full_name} tidak bisa dibaca ({msg}); sprint lanjut tanpa PR."})
        return None, None


def _claim(dept: str) -> str:
    if dept in _running:
        raise HTTPException(409, f"Departemen {dept} masih bekerja, tunggu selesai")
    _running.add(dept)
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- REST
@app.get("/api/health")
def health():
    return {"ok": True, "llm_enabled": settings.llm_enabled, "busy": sorted(_running), "project_db": projects.backend}


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
    if req.project_id is not None:
        if not await projects.get_project(req.project_id):
            raise HTTPException(404, "Proyek tidak ditemukan")
        project_id = req.project_id
    else:
        project_id = (await projects.ensure_project(DEFAULT_PROJECT)).id
    sid = _claim("it")
    try:
        await projects.create_run(sid, project_id, req.prompt)
        store.create_session(sid, "it", req.prompt)
    except Exception:
        _running.discard("it")
        raise
    asyncio.create_task(_it_job(req, sid, project_id))
    return {"session_id": sid, "project_id": project_id}


@app.get("/api/projects")
async def list_projects():
    return await projects.list_projects()


@app.post("/api/projects", status_code=201)
async def create_project(body: ProjectIn):
    repo = (body.repo or "").strip() or None
    check = await _check_repo(repo) if repo else None
    try:
        p = await projects.create_project(body.name, body.description, repo, body.base_branch or None)
    except ProjectExists:
        raise HTTPException(409, "Nama proyek sudah dipakai")
    return {**p, "github": check}


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: int, body: ProjectPatch):
    fields: dict = {}
    check = None
    if body.description is not None:
        fields["description"] = body.description.strip()
    if body.repo is not None:
        repo = body.repo.strip()
        if repo:
            check = await _check_repo(repo)
        fields["repo_full_name"] = repo or None
    if body.base_branch is not None:
        fields["base_branch"] = body.base_branch.strip() or None
    p = await projects.update_project(project_id, **fields)
    if not p:
        raise HTTPException(404, "Proyek tidak ditemukan")
    return {**p, "github": check}


@app.get("/api/github/status")
async def github_status():
    if not settings.github_token:
        return {"configured": False}
    async with GitHubClient() as gh:
        try:
            return {"configured": True, "login": (await gh.user()).get("login")}
        except GitHubError as e:
            return {"configured": True, "error": f"Token ditolak GitHub ({e.status})"}


@app.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(project_id: int):
    if "it" in _running:
        raise HTTPException(409, "Tim IT masih bekerja, tunggu selesai")
    if not await projects.delete_project(project_id):
        raise HTTPException(404, "Proyek tidak ditemukan")


@app.get("/api/projects/{project_id}/runs")
async def project_runs(project_id: int, limit: int = 20):
    if not await projects.get_project(project_id):
        raise HTTPException(404, "Proyek tidak ditemukan")
    return await projects.list_runs(project_id, min(limit, 100))


@app.get("/api/it/runs/{run_id}")
async def it_run(run_id: str):
    run = await projects.get_run(run_id)
    if not run:
        raise HTTPException(404, "Sprint tidak ditemukan")
    return run


@app.get("/api/news/{symbol}")
async def news(symbol: str):
    if not re.fullmatch(r"[A-Za-z0-9./=\-]{2,15}", symbol):
        raise HTTPException(422, "Simbol tidak valid")
    return (await load_news(resolve(symbol))).to_dict()


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
    await sio.emit("hello", {"agents": agents(), "llm_enabled": settings.llm_enabled, "busy": sorted(_running),
                             "project_db": projects.backend}, to=sid)


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
