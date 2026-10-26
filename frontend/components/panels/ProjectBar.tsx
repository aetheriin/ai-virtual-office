"use client";

import { useState } from "react";
import { useOffice } from "@/lib/store";

const VERDICT_COLOR: Record<string, string> = { PASS: "#4dff7c", CHANGES_REQUESTED: "#ff8a2a" };

function when(iso: string) {
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Project picker, "new project" form and sprint history (stored in PostgreSQL). */
export function ProjectBar() {
  const projects = useOffice((s) => s.projects);
  const projectId = useOffice((s) => s.projectId);
  const runs = useOffice((s) => s.runs);
  const viewingRun = useOffice((s) => s.viewingRun);
  const busy = useOffice((s) => s.busy.it);
  const projectDb = useOffice((s) => s.projectDb);
  const selectProject = useOffice((s) => s.selectProject);
  const createProject = useOffice((s) => s.createProject);
  const openRun = useOffice((s) => s.openRun);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) return;
    setSaving(true);
    const ok = await createProject(name.trim(), desc.trim());
    setSaving(false);
    if (ok) { setAdding(false); setName(""); setDesc(""); }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-2">
        <label className="min-w-0 flex-1">
          <span className="font-pixel flex justify-between text-[8px] text-white/60">
            <span>PROYEK</span>
            {projectDb && <span className={projectDb === "postgresql" ? "text-neon-green" : "text-neon-orange"}>{projectDb.toUpperCase()}</span>}
          </span>
          <select className="field" value={projectId ?? ""} disabled={busy || projects.length === 0}
            onChange={(e) => void selectProject(Number(e.target.value))}>
            {projects.length === 0 && <option value="">memuat...</option>}
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.runs})</option>)}
          </select>
        </label>
        <button type="button" onClick={() => setAdding(!adding)} disabled={busy}
          className="btn h-[38px] border-neon-green/60 text-neon-green hover:bg-neon-green/10" aria-expanded={adding}>
          {adding ? "Batal" : "+ Baru"}
        </button>
      </div>

      {adding && (
        <form onSubmit={submit} className="panel space-y-2 p-2">
          <input className="field" placeholder="Nama proyek (mis. Timbangan Sawit)" maxLength={120} value={name}
            onChange={(e) => setName(e.target.value)} autoFocus />
          <input className="field" placeholder="Deskripsi singkat (opsional)" maxLength={4000} value={desc}
            onChange={(e) => setDesc(e.target.value)} />
          <button type="submit" disabled={saving || name.trim().length < 2}
            className="btn w-full border-neon-green text-neon-green hover:bg-neon-green/10">
            {saving ? "Menyimpan..." : "Buat Proyek"}
          </button>
        </form>
      )}

      {runs.length > 0 && (
        <details className="panel px-3 py-2">
          <summary className="font-pixel cursor-pointer text-[8px] text-white/70">RIWAYAT SPRINT ({runs.length})</summary>
          <ul className="font-term mt-2 max-h-48 space-y-1 overflow-y-auto text-[16px] leading-[18px]">
            {runs.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => void openRun(r.id)} disabled={busy}
                  className={`w-full rounded-sm px-1 py-0.5 text-left hover:bg-white/5 ${viewingRun === r.id ? "bg-neon-cyan/10" : ""}`}>
                  <span className="block truncate text-white/85">{r.prompt}</span>
                  <span className="text-[14px] text-white/40">
                    {when(r.created_at)} ·{" "}
                    <span style={{ color: r.status === "failed" ? "#ff4d5e" : VERDICT_COLOR[r.review_verdict ?? ""] ?? "#9aa6c2" }}>
                      {r.status === "done" ? r.review_verdict ?? "selesai" : r.status}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      {viewingRun && <p className="font-term text-[15px] text-neon-cyan">Menampilkan sprint dari riwayat.</p>}
    </div>
  );
}
