"""Turn coder-agent replies into files, and decide which files are safe to put in a pull request."""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from ..config import settings

FILE_BLOCK = re.compile(
    r"^#{2,4}\s*FILE:\s*`?(?P<path>[^\n`]+?)`?\s*\n+```(?P<lang>[\w+#.-]*)[^\n]*\n(?P<body>.*?)\n```",
    re.M | re.S,
)
ANY_BLOCK = re.compile(r"```(?P<lang>[\w+#.-]*)[^\n]*\n(?P<body>.*?)\n```", re.S)

LANG_BY_EXT = {
    ".py": "python", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx", ".sql": "sql", ".html": "html",
    ".css": "css", ".md": "markdown", ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
    ".php": "php", ".go": "go", ".rs": "rust", ".java": "java", ".sh": "bash",
}

# Never let an agent write these: secrets, git internals, CI that could exfiltrate secrets
BLOCKED_PATTERNS = [
    (re.compile(r"(^|/)\.git(/|$)"), "folder .git"),
    (re.compile(r"(^|/)\.github/workflows/"), "workflow GitHub Actions (butuh review manusia)"),
    (re.compile(r"(^|/)\.env(\.(?!example$)[^/]+)?$"), "file rahasia .env"),
    (re.compile(r"\.(pem|key|p12|pfx|keystore|jks)$", re.I), "kunci/sertifikat privat"),
    (re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)(\.pub)?$"), "kunci SSH"),
    (re.compile(r"(^|/)node_modules/|(^|/)\.venv/|(^|/)__pycache__/"), "folder dependensi/build"),
]


@dataclass
class AgentFile:
    path: str | None      # None = snippet without a target path (can't go into a PR)
    content: str
    language: str
    agent: str


@dataclass
class FilePlan:
    accepted: list[AgentFile] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    snippets: list[AgentFile] = field(default_factory=list)


def language_for(path: str | None, fence: str = "") -> str:
    if fence:
        return fence.lower()[:16]
    ext = posixpath.splitext(path or "")[1].lower()
    return LANG_BY_EXT.get(ext, "text")


def parse_files(text: str, agent: str) -> list[AgentFile]:
    """Files written as '### FILE: path' + fenced block. Code without a header becomes a snippet."""
    files = [
        AgentFile(m["path"].strip(), m["body"].rstrip() + "\n", language_for(m["path"], m["lang"]), agent)
        for m in FILE_BLOCK.finditer(text or "")
    ]
    if not files:
        files = [AgentFile(None, m["body"].rstrip() + "\n", language_for(None, m["lang"]), agent)
                 for m in ANY_BLOCK.finditer(text or "")]
    return files


def normalize_path(raw: str) -> tuple[str | None, str | None]:
    """(clean path, None) or (None, reason)."""
    p = raw.strip().strip("`'\"").replace("\\", "/")
    if not p:
        return None, "path kosong"
    if p.startswith("/") or re.match(r"^[a-zA-Z]:", p):
        return None, "path absolut"
    if any(part == ".." for part in p.split("/")):
        return None, "keluar dari folder repo (..)"
    if p.endswith("/"):
        return None, "bukan file"
    p = posixpath.normpath(p)  # "./a//b" -> "a/b"
    if p in (".", ""):
        return None, "bukan file"
    if len(p) > 300 or not re.fullmatch(r"[\w@+\-./ ()\[\]]+", p):
        return None, "nama file tidak valid"
    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(p):
            return None, reason
    return p, None


def plan_files(files: list[AgentFile | dict]) -> FilePlan:
    plan = FilePlan()
    by_path: dict[str, AgentFile] = {}
    max_bytes = int(settings.pr_max_file_kb * 1024)
    for f in files:
        if isinstance(f, dict):
            f = AgentFile(f.get("path"), str(f.get("content", "")), str(f.get("language", "text")), str(f.get("agent", "")))
        if f.path is None:
            plan.snippets.append(f)
            continue
        path, reason = normalize_path(f.path)
        if reason:
            plan.rejected.append((f.path, reason))
            continue
        if len(f.content.encode()) > max_bytes:
            plan.rejected.append((path, f"lebih dari {settings.pr_max_file_kb:g} KB"))
            continue
        by_path[path] = AgentFile(path, f.content, f.language, f.agent)  # later agent wins on the same path
    accepted = list(by_path.values())
    if len(accepted) > settings.pr_max_files:
        for f in accepted[settings.pr_max_files:]:
            plan.rejected.append((f.path, f"melebihi batas {settings.pr_max_files} file per PR"))
        accepted = accepted[: settings.pr_max_files]
    plan.accepted = accepted
    return plan
