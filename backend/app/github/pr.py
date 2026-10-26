"""Repo context for the IT agents, and turning a finished sprint into a pull request.

Safety rules (enforced here, not left to the model):
- never push to the base branch; every sprint gets its own `ai/...` branch and a PR
- the only direct commit is a README that initialises an *empty* repository (GitHub can't branch from nothing)
- unsafe paths (.env, keys, .git, workflows, `..`) and oversized files are dropped and listed in the PR
- a sprint QA didn't pass, or with high findings, opens as a draft
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..config import settings
from .client import GitHubClient, GitHubError
from .files import FilePlan, plan_files

log = logging.getLogger(__name__)

KEY_FILES = ["README.md", "package.json", "requirements.txt", "pyproject.toml", "composer.json", "go.mod", "Cargo.toml"]
MAX_TREE = 300
MAX_KEY_FILE = 4000
MAX_EXISTING_FILE = 12000
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def valid_repo_name(name: str) -> bool:
    return bool(REPO_RE.fullmatch(name)) and not name.endswith((".git", "/."))


@dataclass
class RepoContext:
    repo: str
    base: str
    empty: bool
    paths: list[str]
    brief: str                    # text given to PM / coders
    base_sha: str | None = None

    def exists(self, path: str) -> bool:
        return path in self.paths


async def load_repo_context(gh: GitHubClient, repo: str, base: str | None) -> RepoContext:
    info = await gh.repo(repo)
    base = base or info.default_branch
    if await gh.is_empty(repo):
        return RepoContext(repo, base, True, [], (
            f"REPO GITHUB: {repo} (masih KOSONG).\n"
            "Ini proyek baru: rancang kerangka proyek dari nol (struktur folder, README, file konfigurasi/dependensi, "
            "halaman/endpoint pertama, dan tes dasar)."
        ))
    sha = await gh.branch_sha(repo, base)
    if not sha:
        raise GitHubError(404, f"branch '{base}' tidak ada di {repo}")
    blobs, truncated = await gh.tree(repo, sha)
    paths = [b["path"] for b in blobs]
    parts = [f"REPO GITHUB: {repo} (branch {base}, {len(paths)} file{'+, daftar terpotong' if truncated else ''}).",
             "STRUKTUR FILE:", *paths[:MAX_TREE]]
    if len(paths) > MAX_TREE:
        parts.append(f"... dan {len(paths) - MAX_TREE} file lain")
    for name in KEY_FILES:
        if name in paths:
            text = await gh.file_text(repo, name, sha)
            if text:
                parts += [f"\nISI {name}:", text[:MAX_KEY_FILE]]
    return RepoContext(repo, base, False, paths, "\n".join(parts), sha)


async def read_existing(gh: GitHubClient, ctx: RepoContext, paths: list[str], limit: int = 4) -> dict[str, str]:
    """Current contents of files an agent is about to change, so it edits instead of blindly overwriting."""
    out: dict[str, str] = {}
    for p in [p for p in paths if ctx.exists(p)][:limit]:
        text = await gh.file_text(ctx.repo, p, ctx.base_sha or ctx.base)
        if text is not None:
            out[p] = text[:MAX_EXISTING_FILE]
    return out


# --------------------------------------------------------------------------- PR body
def _slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].rstrip("-") or "sprint")


def branch_name(prompt: str, run_id: str) -> str:
    return f"{settings.pr_branch_prefix}{_slug(prompt)}-{run_id[:6]}"


def needs_draft(review: dict) -> bool:
    findings = [f for f in review.get("findings") or [] if isinstance(f, dict)]
    return str(review.get("verdict", "")).upper() != "PASS" or any(str(f.get("severity", "")).lower() == "high" for f in findings)


def pr_body(state: dict, files: FilePlan, run_id: str, ctx: RepoContext) -> str:
    plan, analysis, review = state.get("plan") or {}, state.get("analysis") or {}, state.get("review") or {}
    lines = [
        f"> 🤖 Dibuat otomatis oleh tim agen **AI Virtual Office** (sprint `{run_id}`). "
        "Kode dari model AI — **review dan uji sebelum merge.**",
        "",
        "## Brief",
        state.get("prompt", ""),
        "",
        "## Rencana PM",
        plan.get("summary", "-"),
    ]
    if plan.get("assumptions"):
        lines += ["", "**Asumsi (perlu konfirmasi):**", *[f"- {a}" for a in plan["assumptions"]]]
    if plan.get("tasks"):
        lines += ["", "**Task:**", *[f"- [x] {t.get('id', '')} {t.get('title', '')} → `{t.get('assignee', '')}`"
                                     for t in plan["tasks"] if isinstance(t, dict)]]
    if analysis.get("acceptance_criteria"):
        lines += ["", "## Acceptance criteria", *[f"- [ ] {a}" for a in analysis["acceptance_criteria"]]]
    if analysis.get("open_questions"):
        lines += ["", "## Pertanyaan dari Analis", *[f"- {q}" for q in analysis["open_questions"]]]

    lines += ["", "## Perubahan file", *[f"- `{f.path}` ({f.agent.upper()}{', ubah' if ctx.exists(f.path) else ', baru'})"
                                          for f in files.accepted]]
    if files.rejected:
        lines += ["", "**Tidak disertakan (ditolak pengaman):**", *[f"- `{p}` — {why}" for p, why in files.rejected]]
    if files.snippets:
        lines += ["", f"_{len(files.snippets)} potongan kode tanpa nama file tidak disertakan; lihat panel Dept. IT._"]

    verdict = review.get("verdict", "-")
    lines += ["", f"## Review QA: `{verdict}`"]
    for f in review.get("findings") or []:
        if isinstance(f, dict):
            lines.append(f"- **{str(f.get('severity', '')).upper()}** ({f.get('agent', '')}): {f.get('issue', '')}")
    if review.get("tests"):
        lines += ["", "**Usulan tes:**", *[f"- {t}" for t in review["tests"]]]
    if needs_draft(review):
        lines += ["", "_PR dibuka sebagai draft karena QA belum `PASS` atau ada temuan high._"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- open the PR
@dataclass
class PrResult:
    status: str                 # opened | draft | skipped | failed
    url: str | None = None
    number: int | None = None
    branch: str | None = None
    error: str | None = None
    files: int = 0


async def open_sprint_pr(gh: GitHubClient, ctx: RepoContext, state: dict, run_id: str, project_name: str) -> PrResult:
    files = plan_files(state.get("files") or [])
    if not files.accepted:
        reason = "tidak ada file dengan path yang valid"
        if files.rejected:
            reason += " (" + "; ".join(f"{p}: {w}" for p, w in files.rejected[:3]) + ")"
        return PrResult("skipped", error=reason)

    repo, base = ctx.repo, ctx.base
    parent = ctx.base_sha
    if ctx.empty:
        # GitHub can't create a branch in a repo without commits: initialise it with a README
        parent = await gh.put_file(
            repo, "README.md", f"# {project_name}\n\nDikelola oleh tim agen AI Virtual Office.\n",
            "Initial commit (AI Virtual Office)", branch=base,
        )
    else:
        parent = await gh.branch_sha(repo, base) or parent  # base may have moved since the sprint started
    if not parent:
        return PrResult("failed", error=f"branch '{base}' tidak ditemukan")

    branch = branch_name(state.get("prompt", ""), run_id)
    title = (state.get("plan") or {}).get("summary") or state.get("prompt", "Sprint AI")
    title = re.sub(r"\s+", " ", str(title)).strip()[:120]
    sha = await gh.commit_files(
        repo, parent, {f.path: f.content for f in files.accepted},
        f"{title}\n\nGenerated by AI Virtual Office IT agents (sprint {run_id}).",
    )
    await gh.create_branch(repo, branch, sha)
    draft = needs_draft(state.get("review") or {})
    pr = await gh.open_pr(repo, title=title, head=branch, base=base, body=pr_body(state, files, run_id, ctx), draft=draft)
    try:
        await gh.add_labels(repo, pr["number"], ["ai-agent"])
    except GitHubError as e:  # labels are a nicety; missing permission shouldn't fail the sprint
        log.info("could not label PR: %s", e)
    return PrResult("draft" if pr.get("draft") or pr.get("title", "").startswith("[WIP]") else "opened",
                    pr.get("html_url"), pr.get("number"), branch, files=len(files.accepted))
