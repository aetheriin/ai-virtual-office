"""In-memory GitHub REST API (the subset GitHubClient uses), served through httpx.MockTransport.

Behaves like the real thing where it matters for the PR flow:
- an empty repository answers 409 on refs and has no branches; only the Contents API can create the first commit
- trees are built on top of a base tree, so untouched files survive a commit
- creating an existing ref is 422; draft PRs can be disabled (free private repos) -> 422
"""
from __future__ import annotations

import base64
import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx

TOKEN = "good-token"


@dataclass
class FakeRepo:
    name: str
    default_branch: str = "main"
    private: bool = True
    push: bool = True
    drafts: bool = True
    labels_allowed: bool = True
    refs: dict[str, str] = field(default_factory=dict)
    commits: dict[str, dict] = field(default_factory=dict)
    trees: dict[str, dict[str, str]] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=dict)
    pulls: list[dict] = field(default_factory=list)
    labels: dict[int, list[str]] = field(default_factory=dict)

    def files_at(self, ref: str) -> dict[str, str]:
        sha = self.refs.get(ref, ref)
        tree = self.trees[self.commits[sha]["tree"]]
        return {p: self.blobs[b] for p, b in tree.items()}


class FakeGitHub:
    def __init__(self):
        self.repos: dict[str, FakeRepo] = {}
        self.calls: list[tuple[str, str]] = []
        self._n = itertools.count(1)

    # ---------------------------------------------------------------- setup helpers
    def _sha(self, *parts: str) -> str:
        return hashlib.sha1("|".join([*parts, str(next(self._n))]).encode()).hexdigest()

    def add_repo(self, name: str, files: dict[str, str] | None = None, **kw) -> FakeRepo:
        repo = FakeRepo(name, **kw)
        self.repos[name] = repo
        if files is not None:
            tree = {}
            for p, text in files.items():
                b = self._sha("blob", text)
                repo.blobs[b] = text
                tree[p] = b
            t = self._sha("tree")
            repo.trees[t] = tree
            c = self._sha("commit")
            repo.commits[c] = {"tree": t, "parents": [], "message": "init"}
            repo.refs[repo.default_branch] = c
        return repo

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # ---------------------------------------------------------------- routing
    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path))
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return _err(401, "Bad credentials")
        path = unquote(req.url.path)
        body = json.loads(req.content) if req.content else {}
        if path == "/user":
            return _ok({"login": "tester"})
        m = re.match(r"^/repos/([^/]+/[^/]+)(/.*)?$", path)
        if not m or m[1] not in self.repos:
            return _err(404, "Not Found")
        repo, rest = self.repos[m[1]], m[2] or ""
        empty = not repo.refs

        if req.method == "GET" and rest == "":
            return _ok({"full_name": repo.name, "default_branch": repo.default_branch, "private": repo.private,
                        "permissions": {"push": repo.push, "pull": True}, "html_url": f"https://github.com/{repo.name}"})
        if req.method == "GET" and rest == "/branches":
            return _ok([{"name": b} for b in repo.refs])
        if req.method == "GET" and (mm := re.match(r"^/git/ref/heads/(.+)$", rest)):
            if empty:
                return _err(409, "Git Repository is empty.")
            sha = repo.refs.get(mm[1])
            return _ok({"object": {"sha": sha}}) if sha else _err(404, "Not Found")
        if req.method == "GET" and (mm := re.match(r"^/git/trees/(\w+)$", rest)):
            tree = repo.trees.get(repo.commits.get(mm[1], {}).get("tree", mm[1]))
            if tree is None:
                return _err(404, "Not Found")
            return _ok({"tree": [{"path": p, "type": "blob", "sha": b} for p, b in tree.items()], "truncated": False})
        if req.method == "GET" and (mm := re.match(r"^/contents/(.+)$", rest)):
            if empty:
                return _err(404, "This repository is empty.")
            ref = req.url.params.get("ref", repo.default_branch)
            text = repo.files_at(ref).get(mm[1])
            if text is None:
                return _err(404, "Not Found")
            return _ok({"type": "file", "encoding": "base64", "content": base64.b64encode(text.encode()).decode()})
        if req.method == "PUT" and (mm := re.match(r"^/contents/(.+)$", rest)):
            if not repo.push:
                return _err(403, "Resource not accessible by personal access token")
            branch = body.get("branch", repo.default_branch)
            parent = repo.refs.get(branch)
            files = repo.files_at(parent) if parent else {}
            files[mm[1]] = base64.b64decode(body["content"]).decode()
            sha = self._commit(repo, files, [parent] if parent else [], body["message"])
            repo.refs[branch] = sha
            return _ok({"commit": {"sha": sha}}, 201)
        if req.method == "GET" and (mm := re.match(r"^/git/commits/(\w+)$", rest)):
            c = repo.commits.get(mm[1])
            return _ok({"sha": mm[1], "tree": {"sha": c["tree"]}}) if c else _err(404, "Not Found")
        if req.method == "POST" and rest == "/git/blobs":
            if empty:
                return _err(409, "Git Repository is empty.")
            sha = self._sha("blob", body["content"])
            repo.blobs[sha] = body["content"]
            return _ok({"sha": sha}, 201)
        if req.method == "POST" and rest == "/git/trees":
            base = dict(repo.trees.get(body.get("base_tree"), {}))
            for e in body["tree"]:
                if e["sha"] not in repo.blobs:
                    return _err(422, "tree.sha is not a valid blob")
                base[e["path"]] = e["sha"]
            sha = self._sha("tree")
            repo.trees[sha] = base
            return _ok({"sha": sha}, 201)
        if req.method == "POST" and rest == "/git/commits":
            sha = self._sha("commit")
            repo.commits[sha] = {"tree": body["tree"], "parents": body["parents"], "message": body["message"]}
            return _ok({"sha": sha}, 201)
        if req.method == "POST" and rest == "/git/refs":
            name = body["ref"].removeprefix("refs/heads/")
            if name in repo.refs:
                return _err(422, "Reference already exists")
            if not repo.push:
                return _err(403, "Resource not accessible by personal access token")
            repo.refs[name] = body["sha"]
            return _ok({"ref": body["ref"]}, 201)
        if req.method == "POST" and rest == "/pulls":
            if body.get("draft") and not repo.drafts:
                return _err(422, "Validation Failed", [{"message": "Draft pull requests are not supported in this repository."}])
            if body["head"] not in repo.refs or body["base"] not in repo.refs:
                return _err(422, "Validation Failed", [{"message": "head or base does not exist"}])
            number = len(repo.pulls) + 1
            pr = {"number": number, "html_url": f"https://github.com/{repo.name}/pull/{number}",
                  "draft": bool(body.get("draft")), **{k: body[k] for k in ("title", "head", "base", "body")}}
            repo.pulls.append(pr)
            return _ok(pr, 201)
        if req.method == "POST" and (mm := re.match(r"^/issues/(\d+)/labels$", rest)):
            if not repo.labels_allowed:
                return _err(403, "Resource not accessible by personal access token")
            repo.labels[int(mm[1])] = body["labels"]
            return _ok([{"name": n} for n in body["labels"]])
        return _err(404, f"fake: no route {req.method} {rest}")

    def _commit(self, repo: FakeRepo, files: dict[str, str], parents: list[str], message: str) -> str:
        tree = {}
        for p, text in files.items():
            b = self._sha("blob", text)
            repo.blobs[b] = text
            tree[p] = b
        t = self._sha("tree")
        repo.trees[t] = tree
        c = self._sha("commit")
        repo.commits[c] = {"tree": t, "parents": parents, "message": message}
        return c


def _ok(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _err(status: int, message: str, errors: list | None = None) -> httpx.Response:
    return httpx.Response(status, json={"message": message, **({"errors": errors} if errors else {})})
