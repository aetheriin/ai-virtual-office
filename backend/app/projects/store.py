"""Async repository for IT project data (PostgreSQL via asyncpg; SQLite fallback for zero-setup dev)."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from ..config import settings
from .models import Base, ItArtifact, ItRun, ItTask, Project, QaFinding, utcnow

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = "Umum"
VALID_ASSIGNEES = {"pm", "analyst", "db", "be", "fe", "qa"}
VALID_STATUS = {"todo", "doing", "done"}


class ProjectExists(Exception):
    pass


def normalize_url(url: str) -> str:
    """Accept the usual postgres:// / postgresql:// URLs and force the async drivers."""
    if not url:
        return f"sqlite+aiosqlite:///{BACKEND_DIR / 'projects.db'}"
    url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", url)
    url = re.sub(r"^postgresql\+psycopg2?://", "postgresql+asyncpg://", url)
    url = re.sub(r"^sqlite:///", "sqlite+aiosqlite:///", url)
    return url


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _language(code: str) -> str:
    m = re.match(r"\s*```(\w+)", code)
    return (m.group(1).lower() if m else "text")[:16]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def run_summary(r: ItRun) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "prompt": r.prompt, "status": r.status,
        "summary": r.summary, "review_verdict": r.review_verdict,
        "created_at": _iso(r.created_at), "finished_at": _iso(r.finished_at),
    }


class ProjectStore:
    def __init__(self, url: str | None = None):
        self.url = normalize_url(url if url is not None else settings.database_url)
        self.engine: AsyncEngine = create_async_engine(self.url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless enabled per connection
            sa.event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

    @property
    def backend(self) -> str:
        return self.engine.dialect.name  # postgresql | sqlite

    async def init(self, *, migrate: bool = True) -> None:
        """Bring the schema up to date. Alembic for real deployments, create_all for throwaway DBs."""
        if migrate:
            from .migrate import upgrade_head
            await upgrade_head(self.engine)
        else:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        await self.ensure_project(DEFAULT_PROJECT, "Proyek default untuk brief tanpa proyek")

    async def close(self) -> None:
        await self.engine.dispose()

    # ------------------------------------------------------------------ projects
    async def ensure_project(self, name: str, description: str = "") -> Project:
        async with self.session() as s:
            p = await s.scalar(sa.select(Project).where(Project.name == name))
            if p:
                return p
            p = Project(name=name, description=description)
            s.add(p)
            try:
                await s.commit()
            except IntegrityError:  # created concurrently
                await s.rollback()
                return await s.scalar(sa.select(Project).where(Project.name == name))
            return p

    async def create_project(self, name: str, description: str = "") -> dict:
        async with self.session() as s:
            p = Project(name=name.strip(), description=description.strip())
            s.add(p)
            try:
                await s.commit()
            except IntegrityError as exc:
                await s.rollback()
                raise ProjectExists(name) from exc
            return {"id": p.id, "name": p.name, "description": p.description, "runs": 0,
                    "last_run_at": None, "created_at": _iso(p.created_at)}

    async def list_projects(self) -> list[dict]:
        q = (
            sa.select(Project, sa.func.count(ItRun.id), sa.func.max(ItRun.created_at))
            .outerjoin(ItRun, ItRun.project_id == Project.id)
            .group_by(Project.id)
            .order_by(sa.func.coalesce(sa.func.max(ItRun.created_at), Project.created_at).desc())
        )
        async with self.session() as s:
            rows = (await s.execute(q)).all()
        return [
            {"id": p.id, "name": p.name, "description": p.description, "runs": n,
             "last_run_at": _iso(last), "created_at": _iso(p.created_at)}
            for p, n, last in rows
        ]

    async def get_project(self, project_id: int) -> Project | None:
        async with self.session() as s:
            return await s.get(Project, project_id)

    async def delete_project(self, project_id: int) -> bool:
        async with self.session() as s:
            p = await s.get(Project, project_id)
            if not p:
                return False
            await s.delete(p)
            await s.commit()
            return True

    # ------------------------------------------------------------------ runs
    async def create_run(self, run_id: str, project_id: int, prompt: str) -> None:
        async with self.session() as s:
            s.add(ItRun(id=run_id, project_id=project_id, prompt=prompt))
            await s.commit()

    async def set_tasks(self, run_id: str, tasks: list[dict]) -> None:
        async with self.session() as s:
            await s.execute(sa.delete(ItTask).where(ItTask.run_id == run_id))
            seen: set[str] = set()
            for i, t in enumerate(tasks, 1):
                code = str(t.get("id") or f"T{i}")[:16]
                if code in seen:  # LLM sometimes repeats ids
                    code = f"T{i}"
                seen.add(code)
                assignee = str(t.get("assignee", "")).lower()
                s.add(ItTask(
                    run_id=run_id, code=code, title=str(t.get("title", ""))[:2000],
                    assignee=assignee if assignee in VALID_ASSIGNEES else "pm",
                    depends_on=[str(d) for d in t.get("depends_on") or []][:20],
                    done_when=str(t.get("done_when", "")), status="todo",
                ))
            await s.commit()

    async def set_task_status(self, run_id: str, assignee: str, status: str) -> None:
        if status not in VALID_STATUS:
            return
        async with self.session() as s:
            await s.execute(
                sa.update(ItTask).where(ItTask.run_id == run_id, ItTask.assignee == assignee)
                .values(status=status, updated_at=utcnow())
            )
            await s.commit()

    async def finish_run(self, run_id: str, state: dict) -> None:
        plan, review = state.get("plan") or {}, state.get("review") or {}
        async with self.session() as s:
            run = await s.get(ItRun, run_id)
            if not run:
                return
            run.status = "done"
            run.summary = str(plan.get("summary", ""))
            run.assumptions = [str(a) for a in plan.get("assumptions") or []]
            run.analysis = state.get("analysis") or {}
            run.review = review
            run.review_verdict = str(review.get("verdict", ""))[:32] or None
            run.finished_at = utcnow()
            for agent, code in (state.get("code") or {}).items():
                s.add(ItArtifact(run_id=run_id, agent=agent, language=_language(code), content=code))
            for f in review.get("findings") or []:
                if isinstance(f, dict):
                    s.add(QaFinding(run_id=run_id, severity=str(f.get("severity", "low"))[:16].lower(),
                                    agent=str(f.get("agent", ""))[:16], issue=str(f.get("issue", ""))))
            await s.commit()

    async def fail_run(self, run_id: str, error: str) -> None:
        async with self.session() as s:
            await s.execute(sa.update(ItRun).where(ItRun.id == run_id)
                            .values(status="failed", error=error[:4000], finished_at=utcnow()))
            await s.commit()

    async def list_runs(self, project_id: int | None = None, limit: int = 20) -> list[dict]:
        q = sa.select(ItRun).order_by(ItRun.created_at.desc()).limit(limit)
        if project_id is not None:
            q = q.where(ItRun.project_id == project_id)
        async with self.session() as s:
            return [run_summary(r) for r in (await s.scalars(q)).all()]

    async def get_run(self, run_id: str) -> dict | None:
        q = (sa.select(ItRun).where(ItRun.id == run_id)
             .options(selectinload(ItRun.tasks), selectinload(ItRun.artifacts), selectinload(ItRun.findings)))
        async with self.session() as s:
            r = await s.scalar(q)
        if not r:
            return None
        return {
            **run_summary(r),
            "assumptions": r.assumptions, "analysis": r.analysis, "review": r.review, "error": r.error,
            "tasks": [{"id": t.code, "title": t.title, "assignee": t.assignee, "depends_on": t.depends_on,
                       "done_when": t.done_when, "status": t.status} for t in r.tasks],
            "code": {a.agent: a.content for a in r.artifacts},
            "findings": [{"severity": f.severity, "agent": f.agent, "issue": f.issue} for f in r.findings],
        }

    async def open_findings(self, project_id: int, severity: str = "high") -> list[dict]:
        """Recent findings of a severity in this project — fed to the PM as context for the next sprint."""
        q = (sa.select(QaFinding, ItRun.id).join(ItRun, ItRun.id == QaFinding.run_id)
             .where(ItRun.project_id == project_id, QaFinding.severity == severity)
             .order_by(ItRun.created_at.desc()).limit(20))
        async with self.session() as s:
            rows = (await s.execute(q)).all()
        return [{"run_id": rid, "agent": f.agent, "issue": f.issue} for f, rid in rows]
