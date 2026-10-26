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
CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    source TEXT NOT NULL DEFAULT 'analisa',
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    interval TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    entry REAL NOT NULL, stop_loss REAL NOT NULL, tp1 REAL NOT NULL, tp2 REAL NOT NULL,
    quantity REAL, unit TEXT, risk_amount REAL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'tp1', 'closed')),
    tp1_hit INTEGER NOT NULL DEFAULT 0,
    result TEXT, r_multiple REAL, exit_price REAL, closed_at TEXT, last_checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screener_runs (
    id TEXT PRIMARY KEY,
    interval TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_WATCHLIST = ["BBCA", "BBRI", "TLKM", "XAUUSD", "EURUSD", "USDJPY"]


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

    # ------------------------------------------------------------------ paper trading
    def add_paper_trade(self, t: dict) -> int:
        cols = ["session_id", "source", "symbol", "asset_class", "interval", "side", "entry", "stop_loss", "tp1", "tp2",
                "quantity", "unit", "risk_amount", "opened_at"]
        with _lock:
            cur = self.conn.execute(
                f"INSERT INTO paper_trades ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [t.get(c) for c in cols],
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def paper_trades(self, status: str | None = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM paper_trades", []
        if status == "active":
            q += " WHERE status != 'closed'"
        elif status:
            q += " WHERE status = ?"
            args.append(status)
        q += " ORDER BY opened_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(q, args).fetchall()]

    def update_paper_trade(self, trade_id: int, **fields) -> None:
        allowed = {"status", "tp1_hit", "result", "r_multiple", "exit_price", "closed_at", "last_checked_at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        with _lock:
            self.conn.execute(
                f"UPDATE paper_trades SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                [*fields.values(), trade_id],
            )
            self.conn.commit()

    def delete_paper_trade(self, trade_id: int) -> bool:
        with _lock:
            cur = self.conn.execute("DELETE FROM paper_trades WHERE id = ?", (trade_id,))
            self.conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ watchlist & settings
    def watchlist(self) -> list[str]:
        rows = self.conn.execute("SELECT symbol FROM watchlist ORDER BY position").fetchall()
        if not rows and self.get_setting("watchlist_initialised") is None:
            self.set_watchlist(DEFAULT_WATCHLIST)
            return list(DEFAULT_WATCHLIST)
        return [r["symbol"] for r in rows]

    def set_watchlist(self, symbols: list[str]) -> None:
        with _lock:
            self.conn.execute("DELETE FROM watchlist")
            self.conn.executemany("INSERT INTO watchlist (symbol, position) VALUES (?, ?)",
                                  [(sym, i) for i, sym in enumerate(dict.fromkeys(symbols))])
            self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('watchlist_initialised', '1')")
            self.conn.commit()

    def get_setting(self, key: str) -> Any | None:
        row = self.conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        with _lock:
            self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                              (key, json.dumps(value, ensure_ascii=False)))
            self.conn.commit()

    # ------------------------------------------------------------------ screener
    def save_screener(self, run_id: str, interval: str, result: dict) -> None:
        with _lock:
            self.conn.execute("INSERT OR REPLACE INTO screener_runs (id, interval, result_json, created_at) VALUES (?, ?, ?, ?)",
                              (run_id, interval, json.dumps(result, ensure_ascii=False), _now()))
            self.conn.commit()

    def last_screener(self) -> dict | None:
        row = self.conn.execute("SELECT result_json FROM screener_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        return json.loads(row["result_json"]) if row else None

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
