import asyncio

import httpx
import pytest

from app import main


@pytest.fixture
async def client():
    await main.projects.init()
    main._running.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        yield c


@pytest.fixture(autouse=True)
def fast_stream(monkeypatch):
    async def noop(*a, **k):
        return None
    monkeypatch.setattr(main.sio, "emit", noop)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(main.asyncio, "sleep", lambda s: real_sleep(0))


async def _wait_done(client, run_id):
    for _ in range(200):
        r = (await client.get(f"/api/it/runs/{run_id}")).json()
        if r["status"] != "running":
            return r
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish")


async def test_project_endpoints(client):
    r = await client.post("/api/projects", json={"name": "API Proj", "description": "d"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert (await client.post("/api/projects", json={"name": "API Proj"})).status_code == 409
    assert (await client.post("/api/projects", json={"name": " "})).status_code == 422
    assert any(p["id"] == pid for p in (await client.get("/api/projects")).json())
    assert (await client.get("/api/projects/99999/runs")).status_code == 404


async def test_it_request_persists_full_sprint(client):
    pid = (await client.post("/api/projects", json={"name": "Sprint Proj"})).json()["id"]
    r = await client.post("/api/it/request", json={"prompt": "Buatkan halaman login", "project_id": pid})
    assert r.status_code == 202
    run = await _wait_done(client, r.json()["session_id"])
    assert run["status"] == "done"
    assert {t["status"] for t in run["tasks"]} == {"done"}
    assert set(run["code"]) == {"db", "be", "fe"}
    assert run["findings"]
    runs = (await client.get(f"/api/projects/{pid}/runs")).json()
    assert [x["id"] for x in runs] == [run["id"]]

    # second sprint gets the first one as PM context
    ctx = await main._project_context(pid)
    assert "Buatkan halaman login" in ctx


async def test_it_request_unknown_project_releases_lock(client):
    r = await client.post("/api/it/request", json={"prompt": "x y z", "project_id": 99999})
    assert r.status_code == 404
    assert "it" not in main._running


async def test_it_request_defaults_to_default_project(client):
    r = await client.post("/api/it/request", json={"prompt": "tanpa proyek"})
    assert r.status_code == 202
    await _wait_done(client, r.json()["session_id"])
    default = next(p for p in (await client.get("/api/projects")).json() if p["name"] == main.DEFAULT_PROJECT)
    assert r.json()["project_id"] == default["id"]
