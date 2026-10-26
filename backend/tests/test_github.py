import pytest

from app.github.client import GitHubClient, GitHubError
from app.github.files import AgentFile, normalize_path, parse_files, plan_files
from app.github.pr import branch_name, load_repo_context, needs_draft, open_sprint_pr, read_existing, valid_repo_name
from tests.fake_github import TOKEN, FakeGitHub


@pytest.fixture
def fake():
    return FakeGitHub()


@pytest.fixture
async def gh(fake):
    async with GitHubClient(TOKEN, api_url="https://api.github.test", transport=fake.transport()) as c:
        yield c


STATE = {
    "prompt": "Tolong buatkan halaman login",
    "plan": {"summary": "Halaman login + API auth", "assumptions": ["ASUMSI: username+password"],
             "tasks": [{"id": "T1", "title": "API auth", "assignee": "be"}]},
    "analysis": {"acceptance_criteria": ["Password di-hash"], "open_questions": ["Perlu fitur lupa password?"]},
    "review": {"verdict": "PASS", "findings": [{"severity": "low", "agent": "fe", "issue": "spinner"}], "tests": ["login ok"]},
    "files": [
        {"agent": "be", "path": "app/auth.py", "content": "def login():\n    ...\n", "language": "python"},
        {"agent": "fe", "path": "templates/login.html", "content": "<form></form>\n", "language": "html"},
        {"agent": "be", "path": ".env", "content": "SECRET=1\n", "language": "text"},
    ],
}


# --------------------------------------------------------------------------- parsing & safety
def test_parse_files_headers_and_snippets():
    text = (
        "Berikut kodenya:\n\n### FILE: app/models.py\n```python\nclass User: ...\n```\n\n"
        "#### FILE: `web/Login.tsx`\n```tsx\nexport default function Login() {}\n```\n"
    )
    files = parse_files(text, "be")
    assert [(f.path, f.language) for f in files] == [("app/models.py", "python"), ("web/Login.tsx", "tsx")]
    assert files[0].content == "class User: ...\n"
    snippet = parse_files("```sql\nSELECT 1;\n```", "db")
    assert snippet[0].path is None and snippet[0].language == "sql"
    assert parse_files("tanpa kode", "fe") == []


@pytest.mark.parametrize("raw,ok", [
    ("app/auth.py", "app/auth.py"),
    ("./src//index.ts", "src/index.ts"),
    ("src\\\\win\\\\path.ts".replace("\\\\", "\\"), "src/win/path.ts"),
    (".env.example", ".env.example"),
    ("docs/README.md", "docs/README.md"),
])
def test_normalize_path_accepts(raw, ok):
    assert normalize_path(raw) == (ok, None)


@pytest.mark.parametrize("raw,reason", [
    ("../etc/passwd", ".."), ("/etc/passwd", "absolut"), ("C:/x.py", "absolut"),
    (".env", ".env"), ("config/.env.production", ".env"), (".git/config", ".git"),
    (".github/workflows/deploy.yml", "workflow"), ("certs/server.key", "kunci"), ("home/id_rsa", "SSH"),
    ("node_modules/x/index.js", "dependensi"), ("", "kosong"), ("a/b/", "bukan file"), ("bad\nname.py", "tidak valid"),
])
def test_normalize_path_rejects(raw, reason):
    path, why = normalize_path(raw)
    assert path is None and reason in why


def test_plan_files_limits_and_dedupe(patch_settings):
    patch_settings(pr_max_files=2, pr_max_file_kb=1)
    plan = plan_files([
        AgentFile("a.py", "v1\n", "python", "be"),
        AgentFile("a.py", "v2\n", "python", "fe"),          # later agent wins
        AgentFile("big.txt", "x" * 2048, "text", "be"),     # > 1 KB
        AgentFile("b.py", "b\n", "python", "be"),
        AgentFile("c.py", "c\n", "python", "be"),           # over the 2-file limit
        AgentFile(None, "snippet\n", "sql", "db"),
        {"agent": "db", "path": "../x.sql", "content": "x"},
    ])
    assert [(f.path, f.content) for f in plan.accepted] == [("a.py", "v2\n"), ("b.py", "b\n")]
    reasons = dict(plan.rejected)
    assert "KB" in reasons["big.txt"] and "batas" in reasons["c.py"] and ".." in reasons["../x.sql"]
    assert len(plan.snippets) == 1


def test_helpers():
    assert valid_repo_name("aetheriin/toko-online") and not valid_repo_name("bad name/x") and not valid_repo_name("x")
    assert branch_name("Buatkan halaman Login!!", "abcdef123") == "ai/buatkan-halaman-login-abcdef"
    assert not needs_draft({"verdict": "PASS", "findings": [{"severity": "low"}]})
    assert needs_draft({"verdict": "PASS", "findings": [{"severity": "HIGH"}]})
    assert needs_draft({"verdict": "CHANGES_REQUESTED"})


# --------------------------------------------------------------------------- against the fake GitHub
async def test_context_of_existing_repo(fake, gh):
    fake.add_repo("me/web", {"README.md": "# Web\nFlask app", "app/__init__.py": "", "requirements.txt": "flask\n"})
    ctx = await load_repo_context(gh, "me/web", None)
    assert not ctx.empty and ctx.base == "main" and ctx.base_sha
    assert "app/__init__.py" in ctx.brief and "Flask app" in ctx.brief and "flask" in ctx.brief
    assert await read_existing(gh, ctx, ["requirements.txt", "missing.py"]) == {"requirements.txt": "flask\n"}


async def test_context_errors(fake, gh):
    fake.add_repo("me/web", {"a": "1"})
    with pytest.raises(GitHubError) as e:
        await load_repo_context(gh, "me/web", "develop")
    assert e.value.status == 404
    with pytest.raises(GitHubError):
        await load_repo_context(gh, "me/missing", None)


async def test_open_pr_on_existing_repo(fake, gh):
    repo = fake.add_repo("me/web", {"README.md": "# Web", "app/auth.py": "old\n"})
    main_before = repo.refs["main"]
    ctx = await load_repo_context(gh, "me/web", None)
    res = await open_sprint_pr(gh, ctx, STATE, "run123456", "Web")

    assert res.status == "opened" and res.number == 1 and res.files == 2
    assert res.url == "https://github.com/me/web/pull/1" and res.branch == "ai/tolong-buatkan-halaman-login-run123"
    assert repo.refs["main"] == main_before, "base branch must never be written"
    head = repo.files_at(res.branch)
    assert head["app/auth.py"] == "def login():\n    ...\n"   # changed
    assert head["README.md"] == "# Web"                      # untouched file survives
    assert ".env" not in head                                # blocked
    pr = repo.pulls[0]
    assert pr["base"] == "main" and pr["head"] == res.branch and pr["title"] == "Halaman login + API auth"
    for part in ("Tolong buatkan halaman login", "ASUMSI", "Password di-hash", "lupa password",
                 "`app/auth.py` (BE, ubah)", "`templates/login.html` (FE, baru)", "`.env` — file rahasia",
                 "Review QA: `PASS`", "login ok"):
        assert part in pr["body"], part
    assert repo.labels[1] == ["ai-agent"]


async def test_empty_repo_gets_readme_then_pr(fake, gh):
    repo = fake.add_repo("me/toko-online")  # brand-new repository, no commits
    ctx = await load_repo_context(gh, "me/toko-online", None)
    assert ctx.empty and "KOSONG" in ctx.brief and ctx.base == "main"
    res = await open_sprint_pr(gh, ctx, STATE, "abcdef0000", "Toko Online")
    assert res.status == "opened"
    assert set(repo.files_at("main")) == {"README.md"}                     # only the initial commit on main
    assert "Toko Online" in repo.files_at("main")["README.md"]
    assert set(repo.files_at(res.branch)) == {"README.md", "app/auth.py", "templates/login.html"}


async def test_draft_and_draft_fallback(fake, gh):
    state = {**STATE, "review": {"verdict": "CHANGES_REQUESTED", "findings": [{"severity": "high", "agent": "be", "issue": "x"}]}}
    repo = fake.add_repo("me/a", {"x": "1"})
    res = await open_sprint_pr(gh, await load_repo_context(gh, "me/a", None), state, "run1", "A")
    assert res.status == "draft" and repo.pulls[0]["draft"] is True

    repo2 = fake.add_repo("me/b", {"x": "1"}, drafts=False, labels_allowed=False)  # free private repo
    res2 = await open_sprint_pr(gh, await load_repo_context(gh, "me/b", None), state, "run2", "B")
    assert res2.status == "draft" and repo2.pulls[0]["title"].startswith("[WIP] ")
    assert repo2.labels == {}  # label failure didn't break the PR


async def test_nothing_valid_to_commit_is_skipped(fake, gh):
    repo = fake.add_repo("me/a", {"x": "1"})
    state = {**STATE, "files": [{"agent": "be", "path": ".env", "content": "S=1"}, {"agent": "db", "path": None, "content": "x"}]}
    res = await open_sprint_pr(gh, await load_repo_context(gh, "me/a", None), state, "run1", "A")
    assert res.status == "skipped" and ".env" in res.error
    assert repo.pulls == [] and set(repo.refs) == {"main"}


async def test_base_branch_moved_during_sprint(fake, gh):
    repo = fake.add_repo("me/a", {"x": "1"})
    ctx = await load_repo_context(gh, "me/a", None)
    await gh.put_file("me/a", "y.txt", "someone else pushed\n", "other commit", branch="main")
    res = await open_sprint_pr(gh, ctx, STATE, "run1", "A")
    assert repo.files_at(res.branch)["y.txt"] == "someone else pushed\n"  # built on the latest main


async def test_bad_token(fake):
    fake.add_repo("me/a", {"x": "1"})
    async with GitHubClient("wrong", api_url="https://api.github.test", transport=fake.transport()) as bad:
        with pytest.raises(GitHubError) as e:
            await bad.repo("me/a")
    assert e.value.status == 401
