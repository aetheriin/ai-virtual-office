"""SQLite storage for agent messages (debate log & memory), IT tasks and trading plans."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('it', 'trade')),
    input TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE TABLE IF NOT EXISTS trading_plans (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | None = None):
        self.conn = sqlite3.connect(path or settings.sqlite_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with _lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def create_session(self, session_id: str, kind: str, text: str) -> None:
        with _lock:
            self.conn.execute(
                "INSERT INTO sessions (id, kind, input, created_at) VALUES (?, ?, ?, ?)",
                (session_id, kind, text, _now()),
            )
            self.conn.commit()

    def add_message(self, session_id: str, agent: str, kind: str, content: Any) -> None:
        payload = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        with _lock:
            self.conn.execute(
                "INSERT INTO messages (session_id, agent, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, agent, kind, payload, _now()),
            )
            self.conn.commit()

    def save_plan(self, session_id: str, plan: dict) -> None:
        with _lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO trading_plans (session_id, symbol, status, plan_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, plan["symbol"], plan["status"], json.dumps(plan, ensure_ascii=False), _now()),
            )
            self.conn.commit()

    def recent_sessions(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, kind, input, created_at FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def session_messages(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT agent, kind, content, created_at FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_plans(self, symbol: str | None = None, limit: int = 10) -> list[dict]:
        if symbol:
            rows = self.conn.execute(
                "SELECT plan_json FROM trading_plans WHERE symbol = ? ORDER BY created_at DESC LIMIT ?", (symbol, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT plan_json FROM trading_plans ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(r["plan_json"]) for r in rows]
