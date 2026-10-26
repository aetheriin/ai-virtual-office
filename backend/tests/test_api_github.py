import asyncio

import httpx
import pytest

from app import main
from app.github.client import GitHubClient
from tests.fake_github import TOKEN, FakeGitHub


@pytest.fixture
def fake(monkeypatch, patch_settings):
    gh = FakeGitHub()
    patch_settings(github_token=TOKEN)
    monkeypatch.setattr(main, "GitHubClient",
                        lambda *a, **k: GitHubClient(TOKEN, api_url="https://api.github.test", transport=gh.transport()))
    return gh


@pytest.fixture
async def client(monkeypatch):
    async def noop(*a, **k):
        return None
    monkeypatch.setattr(main.sio, "emit", noop)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(main.asyncio, "sleep", lambda s: real_sleep(0))
    await main.projects.init()
    main._running.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        yield c


async def _sprint(client, project_id, prompt="Buatkan halaman login"):
    r = await client.post("/api/it/request", json={"prompt": prompt, "project_id": project_id})
    assert r.status_code == 202, r.text
    rid = r.json()["session_id"]
    for _ in range(300):
        run = (await client.get(f"/api/it/runs/{rid}")).json()
        if run["status"] != "running" and run["pr"]["status"] != "pending":
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("sprint did not finish")


async def test_create_project_checks_repo_access(client, fake):
    fake.add_repo("me/ok")
    fake.add_repo("me/readonly", push=False)
    bad = await client.post("/api/projects", json={"name": "P1", "repo": "not a repo"})
    assert bad.status_code == 422
    missing = await client.post("/api/projects", json={"name": "P2", "repo": "me/missing"})
    assert missing.status_code == 422 and "akses" in missing.json()["detail"]
    ro = await client.post("/api/projects", json={"name": "P3", "repo": "me/readonly"})
    assert ro.status_code == 422 and "baca" in ro.json()["detail"]
    ok = await client.post("/api/projects", json={"name": "P4", "repo": "me/ok", "base_branch": "main"})
    assert ok.status_code == 201
    assert ok.json()["repo"] == "me/ok" and ok.json()["github"]["checked"] is True


async def test_create_project_without_token_warns(client, patch_settings):
    patch_settings(github_token="")
    r = await client.post("/api/projects", json={"name": "Tanpa Token", "repo": "me/x"})
    assert r.status_code == 201 and r.json()["github"]["checked"] is False


async def test_patch_connects_and_disconnects_repo(client, fake):
    fake.add_repo("me/ok")
    pid = (await client.post("/api/projects", json={"name": "Patch"})).json()["id"]
    r = await client.patch(f"/api/projects/{pid}", json={"repo": "me/ok", "base_branch": "develop"})
    assert r.status_code == 200 and r.json()["repo"] == "me/ok" and r.json()["base_branch"] == "develop"
    r = await client.patch(f"/api/projects/{pid}", json={"repo": ""})
    assert r.json()["repo"] is None
    assert (await client.patch("/api/projects/99999", json={"description": "x"})).status_code == 404


async def test_rule_engine_sprint_does_not_push_templates(client, fake):
    repo = fake.add_repo("me/web", {"README.md": "# web"})
    pid = (await client.post("/api/projects", json={"name": "Rule", "repo": "me/web"})).json()["id"]
    run = await _sprint(client, pid)
    assert run["status"] == "done"
    assert run["pr"]["status"] == "skipped" and "Rule engine" in run["pr"]["error"]
    assert repo.pulls == []


async def test_sprint_opens_pr_on_new_empty_repo(client, fake, patch_settings):
    patch_settings(github_token=TOKEN, allow_template_pr=True)
    repo = fake.add_repo("me/toko-online")
    pid = (await client.post("/api/projects", json={"name": "Toko", "repo": "me/toko-online"})).json()["id"]
    run = await _sprint(client, pid, "Buatkan web toko online")
    assert run["status"] == "done"
    assert run["pr"]["status"] == "draft"  # template QA verdict is CHANGES_REQUESTED
    assert run["pr"]["url"] == "https://github.com/me/toko-online/pull/1"
    files = repo.files_at(run["pr"]["branch"])
    assert {"README.md", "migrations/001_create_buatkan_web_toko.sql", "app/routes/auth.py", "components/LoginForm.tsx"} <= set(files)
    assert set(repo.files_at("main")) == {"README.md"}
    assert [f["path"] for f in run["files"]] == ["migrations/001_create_buatkan_web_toko.sql", "app/routes/auth.py",
                                                 "components/LoginForm.tsx"]
    assert run["code"]["be"].startswith("### FILE: app/routes/auth.py")
    listed = (await client.get(f"/api/projects/{pid}/runs")).json()[0]
    assert listed["pr"]["number"] == 1


async def test_unreadable_repo_fails_pr_but_finishes_sprint(client, fake, patch_settings):
    patch_settings(github_token=TOKEN, allow_template_pr=True)
    fake.add_repo("me/gone", {"x": "1"})
    pid = (await client.post("/api/projects", json={"name": "Gone", "repo": "me/gone"})).json()["id"]
    del fake.repos["me/gone"]  # deleted / access revoked after it was connected
    run = await _sprint(client, pid)
    assert run["status"] == "done"
    assert run["pr"]["status"] == "failed" and "Tidak bisa membaca repo" in run["pr"]["error"]


async def test_project_without_repo_has_no_pr(client, fake):
    pid = (await client.post("/api/projects", json={"name": "Lokal"})).json()["id"]
    run = await _sprint(client, pid)
    assert run["pr"]["status"] == "none"
    assert fake.calls == []


async def test_github_status(client, fake, patch_settings):
    assert (await client.get("/api/github/status")).json() == {"configured": True, "login": "tester"}
    patch_settings(github_token="")
    assert (await client.get("/api/github/status")).json() == {"configured": False}


async def test_network_error_during_pr_keeps_sprint_done(client, fake, monkeypatch, patch_settings):
    patch_settings(github_token=TOKEN, allow_template_pr=True)
    fake.add_repo("me/flaky", {"x": "1"})
    pid = (await client.post("/api/projects", json={"name": "Flaky", "repo": "me/flaky"})).json()["id"]
    real = fake._handle

    def flaky(req):  # repo reads work, the first write times out
        if req.method == "POST":
            raise httpx.ConnectTimeout("timed out", request=req)
        return real(req)

    monkeypatch.setattr(fake, "_handle", flaky)
    run = await _sprint(client, pid)
    assert run["status"] == "done"
    assert run["pr"]["status"] == "failed" and "koneksi" in run["pr"]["error"]
