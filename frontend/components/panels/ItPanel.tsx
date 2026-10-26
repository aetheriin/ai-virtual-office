"use client";

import { useState } from "react";
import { AGENT_BY_ID } from "@/lib/agents";
import { useOffice } from "@/lib/store";

const STATUS_COLOR = { todo: "#ff8a2a", doing: "#5fe6ff", done: "#4dff7c" } as const;
const SEVERITY_COLOR: Record<string, string> = { high: "#ff4d5e", medium: "#ff8a2a", low: "#5fe6ff" };

export function ItPanel() {
  const requestIt = useOffice((s) => s.requestIt);
  const busy = useOffice((s) => s.busy.it);
  const connected = useOffice((s) => s.connected);
  const tasks = useOffice((s) => s.tasks);
  const result = useOffice((s) => s.itResult);
  const [prompt, setPrompt] = useState("Tolong buatkan halaman login untuk timbangan sawit");

  return (
    <div className="space-y-3">
      <form onSubmit={(e) => { e.preventDefault(); if (prompt.trim().length >= 3) void requestIt(prompt.trim()); }} className="space-y-2">
        <label className="font-pixel text-[8px] text-white/60" htmlFor="it-prompt">BRIEF UNTUK PROJECT MANAGER</label>
        <textarea id="it-prompt" className="field min-h-[84px] resize-y" maxLength={4000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <button type="submit" disabled={busy || !connected || prompt.trim().length < 3}
          className="btn w-full border-neon-cyan text-neon-cyan hover:bg-neon-cyan/10">
          {busy ? "Tim IT sedang bekerja..." : "Kirim ke PM"}
        </button>
      </form>

      {tasks.length > 0 && (
        <div className="panel p-3">
          <div className="font-pixel mb-2 text-[9px] text-white">PAPAN TUGAS</div>
          <ul className="font-term space-y-1 text-[17px] leading-5">
            {tasks.map((t) => (
              <li key={t.id} className="flex items-start gap-2">
                <span className="font-pixel mt-1 shrink-0 text-[7px]" style={{ color: STATUS_COLOR[t.status] }}>{t.status.toUpperCase()}</span>
                <span className="text-white/85">
                  {t.id} {t.title} <span className="text-white/40">→ {AGENT_BY_ID[t.assignee]?.short ?? t.assignee}</span>
                  {t.done_when && <span className="block text-white/40">✓ {t.done_when}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result && (
        <div className="panel font-term space-y-3 p-3 text-[17px] leading-5">
          {result.plan.assumptions && result.plan.assumptions.length > 0 && (
            <div>
              <div className="text-neon-orange">Asumsi PM (perlu konfirmasi)</div>
              <ul className="list-inside list-disc text-white/70">{result.plan.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            </div>
          )}
          {result.analysis.acceptance_criteria && (
            <div>
              <div className="text-neon-cyan">Acceptance Criteria</div>
              <ul className="list-inside list-disc text-white/70">{result.analysis.acceptance_criteria.map((a) => <li key={a}>{a}</li>)}</ul>
            </div>
          )}
          {result.analysis.open_questions && result.analysis.open_questions.length > 0 && (
            <div>
              <div className="text-neon-orange">Pertanyaan Analis untuk Anda</div>
              <ul className="list-inside list-disc text-white/70">{result.analysis.open_questions.map((a) => <li key={a}>{a}</li>)}</ul>
            </div>
          )}
          {(["db", "be", "fe"] as const).map((r) => result.code[r] && (
            <details key={r}>
              <summary className="cursor-pointer text-neon-green">Kode {AGENT_BY_ID[r].name}</summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded-sm bg-night-950 p-2 text-[14px] leading-4 text-white/80">
                {result.code[r]!.replace(/^```\w*\n?|```$/gm, "")}
              </pre>
            </details>
          ))}
          <div>
            <div className={result.review.verdict === "PASS" ? "text-neon-green" : "text-neon-orange"}>QA: {result.review.verdict}</div>
            <ul className="space-y-0.5">
              {result.review.findings?.map((f, i) => (
                <li key={i} className="text-white/75">
                  <span style={{ color: SEVERITY_COLOR[f.severity] ?? "#fff" }}>[{f.severity}]</span> {f.agent.toUpperCase()}: {f.issue}
                </li>
              ))}
            </ul>
            {result.review.tests && <div className="mt-1 text-white/50">Test: {result.review.tests.join(" · ")}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
