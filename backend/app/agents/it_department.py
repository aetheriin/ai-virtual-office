"""Departemen IT — PM -> Analyst -> (DB, BE, FE) -> QA.

A small explicit state machine (LangGraph-style nodes, no heavy dependency):
each node reads the shared `state`, calls its model, writes back, and streams
status/messages to the 3D office via `emit`.
"""
from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from ..config import settings
from ..llm import chat, extract_json

Emit = Callable[[str, dict], Awaitable[None]]

SHARED_RULES = (
    "Aturan bersama: jangan berasumsi — pisahkan FAKTA dan ASUMSI secara eksplisit. Rahasia disimpan di .env, "
    "jangan pernah di-hardcode. Kode dalam Bahasa Inggris, penjelasan dalam Bahasa Indonesia."
)

ROLES = {
    "pm": "Project Manager",
    "analyst": "Analis Kebutuhan",
    "db": "Database Engineer",
    "be": "Backend Developer",
    "fe": "Frontend Developer",
    "qa": "QA & Reviewer",
}

PM_SYSTEM = (
    f"Kamu adalah PROJECT MANAGER tim software. {SHARED_RULES} Pecah permintaan menjadi task kecil. "
    "Balas HANYA JSON: {\"summary\": str, \"assumptions\": [str], \"tasks\": [{\"id\": \"T1\", \"title\": str, "
    "\"assignee\": \"analyst|db|be|fe|qa\", \"depends_on\": [str], \"done_when\": str}]}"
)
ANALYST_SYSTEM = (
    f"Kamu adalah ANALIS KEBUTUHAN. {SHARED_RULES} Buat user story, acceptance criteria, edge cases, dan pertanyaan "
    "untuk user bila ada yang ambigu. Balas JSON: {\"user_stories\": [str], \"acceptance_criteria\": [str], "
    "\"edge_cases\": [str], \"open_questions\": [str]}"
)
CODER_SYSTEM = {
    "db": f"Kamu adalah DATABASE ENGINEER. {SHARED_RULES} Rancang skema relasional + migrasi SQL. Beri kode dalam satu blok ```sql.",
    "be": (f"Kamu adalah BACKEND DEVELOPER. {SHARED_RULES} Tulis API (Python) yang aman: query terparameter (anti SQL injection), "
           "hash password (bcrypt/argon2), validasi input, dokumentasi endpoint. Beri kode dalam satu blok kode."),
    "fe": (f"Kamu adalah FRONTEND DEVELOPER. {SHARED_RULES} Tulis komponen Next.js + Tailwind yang responsif dengan validasi "
           "sisi klien dan state loading/error. Beri kode dalam satu blok ```tsx."),
}
QA_SYSTEM = (
    f"Kamu adalah QA & REVIEWER. Kamu TIDAK menulis fitur. {SHARED_RULES} Periksa apakah acceptance criteria terpenuhi, "
    "cari celah keamanan, dan usulkan unit test. Balas JSON: {\"verdict\": \"PASS|CHANGES_REQUESTED\", "
    "\"findings\": [{\"severity\": \"high|medium|low\", \"agent\": \"db|be|fe\", \"issue\": str}], \"tests\": [str]}"
)


# --------------------------------------------------------------------------- offline fallbacks
def _slug(text: str) -> str:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return "_".join(words[:3]) or "feature"


def fallback_plan(prompt: str) -> dict:
    return {
        "summary": f"Rencana kerja untuk: {prompt}",
        "assumptions": ["ASUMSI: autentikasi berbasis username + password", "ASUMSI: database relasional (SQLite/PostgreSQL)"],
        "tasks": [
            {"id": "T1", "title": "Validasi kebutuhan & acceptance criteria", "assignee": "analyst", "depends_on": [], "done_when": "User story & AC disetujui"},
            {"id": "T2", "title": "Desain skema & migrasi", "assignee": "db", "depends_on": ["T1"], "done_when": "Migrasi berjalan bersih"},
            {"id": "T3", "title": "API & logika bisnis", "assignee": "be", "depends_on": ["T2"], "done_when": "Endpoint terdokumentasi & teruji"},
            {"id": "T4", "title": "Komponen UI & integrasi API", "assignee": "fe", "depends_on": ["T3"], "done_when": "UI responsif, state loading/error"},
            {"id": "T5", "title": "Review kode, keamanan & unit test", "assignee": "qa", "depends_on": ["T3", "T4"], "done_when": "Semua AC terpenuhi, tidak ada temuan high"},
        ],
    }


def fallback_analysis(prompt: str) -> dict:
    return {
        "user_stories": [f"Sebagai pengguna, saya ingin {prompt.lower()} agar pekerjaan saya lebih cepat."],
        "acceptance_criteria": ["Input wajib divalidasi di klien dan server", "Pesan error jelas & tidak membocorkan detail internal",
                                "Data sensitif tidak pernah dikirim/log dalam plaintext"],
        "edge_cases": ["Input kosong / terlalu panjang", "Request ganda (double submit)", "Koneksi terputus saat proses"],
        "open_questions": ["Siapa saja role pengguna yang boleh mengakses fitur ini?"],
    }


def fallback_code(role: str, prompt: str) -> str:
    name = _slug(prompt)
    if role == "db":
        return f"""```sql
-- migration: 001_create_{name}.sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_username ON users(username);
```"""
    if role == "be":
        return """```python
from fastapi import APIRouter, Depends, HTTPException
from passlib.hash import bcrypt
from pydantic import BaseModel, Field

from app.deps import get_db, issue_token  # provided by the host app

router = APIRouter(prefix="/api/auth")

class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)

@router.post("/login")
def login(body: LoginIn, db=Depends(get_db)):
    \"\"\"Authenticate a user. Returns 401 with a generic message on failure.\"\"\"
    row = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (body.username,)).fetchone()
    if not row or not bcrypt.verify(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": issue_token(row["id"])}
```"""
    return """```tsx
"use client";
import { useState } from "react";

export default function LoginForm() {
  const [form, setForm] = useState({ username: "", password: "" });
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (form.username.length < 3 || form.password.length < 8) {
      setState("error"); setError("Username min. 3, password min. 8 karakter"); return;
    }
    setState("loading");
    const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    if (!res.ok) { setState("error"); setError("Username atau password salah"); return; }
    setState("idle");
  }

  return (
    <form onSubmit={submit} className="mx-auto flex w-full max-w-sm flex-col gap-3 p-4">
      <input className="rounded border p-2" placeholder="Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
      <input className="rounded border p-2" type="password" placeholder="Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
      {state === "error" && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <button disabled={state === "loading"} className="rounded bg-green-600 p-2 text-white disabled:opacity-50">
        {state === "loading" ? "Memproses..." : "Masuk"}
      </button>
    </form>
  );
}
```"""


def fallback_review() -> dict:
    return {
        "verdict": "CHANGES_REQUESTED",
        "findings": [
            {"severity": "medium", "agent": "be", "issue": "Tambahkan rate limiting pada endpoint login untuk mencegah brute force"},
            {"severity": "low", "agent": "fe", "issue": "Tangani error jaringan (fetch throw) selain status non-OK"},
        ],
        "tests": ["login sukses mengembalikan token", "password salah -> 401 pesan generik", "username < 3 karakter ditolak (422)"],
    }


# --------------------------------------------------------------------------- pipeline
async def _say(emit: Emit, agent: str, kind: str, text: str, data=None) -> None:
    await emit("agent:message", {"agent": agent, "kind": kind, "text": text, "data": data})


def _code_summary(role: str, code: str) -> str:
    lines = [l for l in code.splitlines() if l.strip() and not l.startswith("```")]
    what = {"db": "Skema & migrasi", "be": "API backend", "fe": "Komponen UI"}[role]
    return f"{what} selesai ({len(lines)} baris)."


async def run_it_pipeline(prompt: str, emit: Emit) -> dict:
    state: dict = {"prompt": prompt}

    # PM
    await emit("agent:status", {"agent": "pm", "state": "standing"})
    plan = extract_json(await chat(settings.model_pm, PM_SYSTEM, prompt, prefer_gemini=True, temperature=0.2))
    if not (isinstance(plan, dict) and isinstance(plan.get("tasks"), list) and plan["tasks"]):
        plan = fallback_plan(prompt)
    state["plan"] = plan
    await emit("it:tasks", {"tasks": [dict(t, status="todo") for t in plan["tasks"]]})
    await _say(emit, "pm", "plan", f"{plan.get('summary', '')} — {len(plan['tasks'])} task dibagikan.", plan)
    await emit("agent:status", {"agent": "pm", "state": "idle"})

    def mark(assignee: str, status: str):
        return emit("it:task_status", {"assignee": assignee, "status": status})

    # Analyst
    await emit("agent:status", {"agent": "analyst", "state": "thinking"})
    await mark("analyst", "doing")
    analysis = extract_json(await chat(settings.model_pm, ANALYST_SYSTEM, prompt, prefer_gemini=True, temperature=0.3))
    if not isinstance(analysis, dict):
        analysis = fallback_analysis(prompt)
    state["analysis"] = analysis
    qs = analysis.get("open_questions") or []
    await _say(emit, "analyst", "analysis",
               f"{len(analysis.get('acceptance_criteria', []))} acceptance criteria, {len(analysis.get('edge_cases', []))} edge case."
               + (f" Pertanyaan untuk Anda: {qs[0]}" if qs else ""), analysis)
    await mark("analyst", "done")
    await emit("agent:status", {"agent": "analyst", "state": "idle"})

    # Coders (sequential so each builds on the previous artifact)
    context = f"PERMINTAAN:\n{prompt}\n\nACCEPTANCE CRITERIA:\n{json.dumps(analysis, ensure_ascii=False)}"
    code: dict[str, str] = {}
    for role in ("db", "be", "fe"):
        await emit("agent:status", {"agent": role, "state": "typing"})
        await mark(role, "doing")
        prior = "\n\n".join(f"KODE {r.upper()}:\n{c}" for r, c in code.items())
        out = await chat(settings.model_coder, CODER_SYSTEM[role], f"{context}\n\n{prior}", temperature=0.2)
        code[role] = out or fallback_code(role, prompt)
        await _say(emit, role, "code", _code_summary(role, code[role]), {"code": code[role]})
        await mark(role, "done")
        await emit("agent:status", {"agent": role, "state": "idle"})
    state["code"] = code

    # QA
    await emit("agent:status", {"agent": "qa", "state": "thinking"})
    await mark("qa", "doing")
    review = extract_json(await chat(
        settings.model_pm, QA_SYSTEM, f"{context}\n\n" + "\n\n".join(f"KODE {r.upper()}:\n{c}" for r, c in code.items()),
        prefer_gemini=True, temperature=0.2,
    ))
    if not isinstance(review, dict):
        review = fallback_review()
    state["review"] = review
    findings = review.get("findings", [])
    await _say(emit, "qa", "review", f"Verdict: {review.get('verdict')} — {len(findings)} temuan, {len(review.get('tests', []))} usulan test.", review)
    await mark("qa", "done")
    await emit("agent:status", {"agent": "qa", "state": "idle"})

    await _say(emit, "pm", "done", "Sprint selesai. Cek panel hasil untuk kode & temuan QA.")
    return state
