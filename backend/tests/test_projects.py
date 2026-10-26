"""Project database tests. Runs on SQLite always, and on PostgreSQL when TEST_DATABASE_URL is set, e.g.
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/office_test pytest tests/test_projects.py
"""
import asyncio
import os

import pytest
import sqlalchemy as sa

from app.projects.store import DEFAULT_PROJECT, ProjectExists, ProjectStore, normalize_url

BACKENDS = ["sqlite"] + (["postgresql"] if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
async def db(request, tmp_path):
    if request.param == "sqlite":
        store = ProjectStore(f"sqlite:///{tmp_path}/p.db")
    else:
        store = ProjectStore(os.environ["TEST_DATABASE_URL"])
        async with store.engine.begin() as conn:  # clean slate, incl. alembic_version
            await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            await conn.execute(sa.text("CREATE SCHEMA public"))
    await store.init(migrate=True)  # always exercise the real Alembic migration
    yield store
    await store.close()


STATE = {
    "plan": {"summary": "Login page", "assumptions": ["ASUMSI: username+password"], "tasks": []},
    "analysis": {"acceptance_criteria": ["validasi input"]},
    "code": {"db": "```sql\nCREATE TABLE users();\n```", "be": "```python\nprint(1)\n```", "fe": "no fence"},
    "review": {"verdict": "CHANGES_REQUESTED", "tests": ["t1"],
               "findings": [{"severity": "HIGH", "agent": "be", "issue": "no rate limit"},
                            {"severity": "low", "agent": "fe", "issue": "spinner"}, "garbage"]},
}
TASKS = [
    {"id": "T1", "title": "AC", "assignee": "analyst", "depends_on": [], "done_when": "ok"},
    {"id": "T1", "title": "dup id", "assignee": "BE", "depends_on": ["T1"]},
    {"id": "T3", "title": "weird", "assignee": "intern"},
]


def test_normalize_url():
    assert normalize_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_url("postgresql://u@h:5433/db") == "postgresql+asyncpg://u@h:5433/db"
    assert normalize_url("postgresql+psycopg2://u@h/db") == "postgresql+asyncpg://u@h/db"
    assert normalize_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"
    assert normalize_url("").startswith("sqlite+aiosqlite:///")


async def test_migration_creates_schema_and_default_project(db):
    async with db.engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
        version = (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar()
    assert {"projects", "it_runs", "it_tasks", "it_artifacts", "qa_findings"} <= tables
    assert version == "0001"
    assert [p["name"] for p in await db.list_projects()] == [DEFAULT_PROJECT]
    await db.init()  # idempotent


async def test_projects_crud_and_unique_name(db):
    p = await db.create_project("Timbangan Sawit", "aplikasi timbangan")
    with pytest.raises(ProjectExists):
        await db.create_project("Timbangan Sawit")
    names = [x["name"] for x in await db.list_projects()]
    assert "Timbangan Sawit" in names
    assert await db.delete_project(p["id"]) is True
    assert await db.delete_project(p["id"]) is False


async def test_run_lifecycle(db):
    p = await db.create_project("Proj")
    await db.create_run("run1", p["id"], "Buatkan login")
    await db.set_tasks("run1", TASKS)
    await db.set_task_status("run1", "analyst", "done")
    await db.set_task_status("run1", "be", "bogus")  # ignored
    await db.finish_run("run1", STATE)

    run = await db.get_run("run1")
    assert run["status"] == "done" and run["review_verdict"] == "CHANGES_REQUESTED"
    assert [t["id"] for t in run["tasks"]] == ["T1", "T2", "T3"]  # duplicate id renumbered
    assert [t["assignee"] for t in run["tasks"]] == ["analyst", "be", "pm"]  # unknown -> pm
    assert run["tasks"][0]["status"] == "done" and run["tasks"][1]["status"] == "todo"
    assert run["code"]["db"].startswith("```sql")
    assert run["assumptions"] == ["ASUMSI: username+password"]
    assert run["analysis"]["acceptance_criteria"] == ["validasi input"]
    assert {f["severity"] for f in run["findings"]} == {"high", "low"}  # normalised, junk dropped

    async with db.session() as s:
        langs = (await s.execute(sa.text("SELECT agent, language FROM it_artifacts ORDER BY agent"))).all()
    assert dict(langs) == {"be": "python", "db": "sql", "fe": "text"}

    assert [r["id"] for r in await db.list_runs(p["id"])] == ["run1"]
    assert (await db.list_projects())[0]["runs"] == 1  # most recently active first
    assert [f["issue"] for f in await db.open_findings(p["id"])] == ["no rate limit"]


async def test_fail_run_and_cascade_delete(db):
    p = await db.create_project("Gagal")
    await db.create_run("run2", p["id"], "x")
    await db.set_tasks("run2", TASKS[:1])
    await db.fail_run("run2", "boom")
    run = await db.get_run("run2")
    assert run["status"] == "failed" and run["error"] == "boom" and run["finished_at"]
    await db.delete_project(p["id"])
    assert await db.get_run("run2") is None
    async with db.session() as s:
        assert (await s.execute(sa.text("SELECT count(*) FROM it_tasks"))).scalar() == 0


async def test_run_requires_existing_project(db):
    with pytest.raises(sa.exc.IntegrityError):
        await db.create_run("orphan", 9999, "x")


async def test_concurrent_ensure_project(db):
    results = await asyncio.gather(*(db.ensure_project("Paralel") for _ in range(5)))
    assert len({p.id for p in results}) == 1
