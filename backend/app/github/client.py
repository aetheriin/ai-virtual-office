"""Minimal async GitHub REST client: just what the IT department needs to open pull requests."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ..config import settings


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status
        self.message = message


@dataclass
class RepoInfo:
    full_name: str
    default_branch: str
    private: bool
    can_push: bool
    html_url: str


class GitHubClient:
    def __init__(self, token: str | None = None, *, api_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.token = token if token is not None else settings.github_token
        self.http = httpx.AsyncClient(
            base_url=(api_url or settings.github_api_url).rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ai-virtual-office",
            },
            timeout=30,
            transport=transport,
        )

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, **kw) -> dict | list:
        r = await self.http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("message", r.text)
                if body.get("errors"):
                    msg += " — " + "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in body["errors"])
            except ValueError:
                msg = r.text
            raise GitHubError(r.status_code, msg)
        return r.json() if r.content else {}

    # ------------------------------------------------------------------ reads
    async def user(self) -> dict:
        return await self._req("GET", "/user")

    async def repo(self, full_name: str) -> RepoInfo:
        d = await self._req("GET", f"/repos/{full_name}")
        return RepoInfo(d["full_name"], d.get("default_branch") or "main", bool(d.get("private")),
                        bool((d.get("permissions") or {}).get("push", False)), d.get("html_url", ""))

    async def branch_sha(self, full_name: str, branch: str) -> str | None:
        """Commit sha of a branch; None if the branch doesn't exist. Raises 409 for an empty repo."""
        try:
            d = await self._req("GET", f"/repos/{full_name}/git/ref/heads/{quote(branch, safe='/')}")
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        return d["object"]["sha"]

    async def is_empty(self, full_name: str) -> bool:
        """A repository with no commits at all (GitHub answers 409 'Git Repository is empty.')."""
        try:
            return not await self._req("GET", f"/repos/{full_name}/branches", params={"per_page": 1})
        except GitHubError as e:
            if e.status == 409:
                return True
            raise

    async def tree(self, full_name: str, sha: str) -> tuple[list[dict], bool]:
        d = await self._req("GET", f"/repos/{full_name}/git/trees/{sha}", params={"recursive": "1"})
        return [t for t in d.get("tree", []) if t.get("type") == "blob"], bool(d.get("truncated"))

    async def file_text(self, full_name: str, path: str, ref: str) -> str | None:
        try:
            d = await self._req("GET", f"/repos/{full_name}/contents/{quote(path)}", params={"ref": ref})
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        if not isinstance(d, dict) or d.get("type") != "file" or d.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(d.get("content", "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None  # binary file

    # ------------------------------------------------------------------ writes
    async def put_file(self, full_name: str, path: str, text: str, message: str, branch: str | None = None) -> str:
        """Contents API — the only write that works on an empty repository (creates its first commit)."""
        body = {"message": message, "content": base64.b64encode(text.encode()).decode()}
        if branch:
            body["branch"] = branch
        d = await self._req("PUT", f"/repos/{full_name}/contents/{quote(path)}", json=body)
        return d["commit"]["sha"]

    async def commit_files(self, full_name: str, parent_sha: str, files: dict[str, str], message: str) -> str:
        """Create one commit on top of `parent_sha` containing `files` (path -> text). Returns the commit sha."""
        base_tree = (await self._req("GET", f"/repos/{full_name}/git/commits/{parent_sha}"))["tree"]["sha"]
        entries = []
        for path, text in files.items():
            blob = await self._req("POST", f"/repos/{full_name}/git/blobs", json={"content": text, "encoding": "utf-8"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = await self._req("POST", f"/repos/{full_name}/git/trees", json={"base_tree": base_tree, "tree": entries})
        commit = await self._req("POST", f"/repos/{full_name}/git/commits",
                                 json={"message": message, "tree": tree["sha"], "parents": [parent_sha]})
        return commit["sha"]

    async def create_branch(self, full_name: str, branch: str, sha: str) -> None:
        await self._req("POST", f"/repos/{full_name}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})

    async def open_pr(self, full_name: str, *, title: str, head: str, base: str, body: str, draft: bool) -> dict:
        try:
            return await self._req("POST", f"/repos/{full_name}/pulls",
                                   json={"title": title, "head": head, "base": base, "body": body, "draft": draft})
        except GitHubError as e:
            # Draft PRs need a paid plan on private repos: fall back to a normal PR marked [WIP]
            if draft and e.status == 422 and "draft" in e.message.lower():
                return await self._req("POST", f"/repos/{full_name}/pulls",
                                       json={"title": f"[WIP] {title}", "head": head, "base": base, "body": body})
            raise

    async def add_labels(self, full_name: str, number: int, labels: list[str]) -> None:
        await self._req("POST", f"/repos/{full_name}/issues/{number}/labels", json={"labels": labels})
