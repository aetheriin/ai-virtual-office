"use client";

import { useEffect, useState } from "react";
import { useOffice } from "@/lib/store";
import type { Project, RunSummary } from "@/lib/types";

const VERDICT_COLOR: Record<string, string> = { PASS: "#4dff7c", CHANGES_REQUESTED: "#ff8a2a" };
const REPO_RE = /^[A-Za-z0-9-]{1,39}\/[A-Za-z0-9._-]{1,100}$/;

function when(iso: string) {
  return new Date(iso).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function PrBadge({ run }: { run: RunSummary }) {
  const pr = run.pr;
  if (!pr || pr.status === "none") return null;
  const color = { opened: "#4dff7c", draft: "#5fe6ff", pending: "#9aa6c2", skipped: "#9aa6c2", failed: "#ff4d5e" }[pr.status];
  return <span style={{ color }}> · {pr.number ? `PR #${pr.number}` : "PR"} {pr.status === "draft" ? "draft" : pr.status === "opened" ? "" : pr.status}</span>;
}

/** Shows / edits the GitHub repo linked to the selected project. */
function RepoLine({ project }: { project: Project }) {
  const updateProject = useOffice((s) => s.updateProject);
  const github = useOffice((s) => s.github);
  const busy = useOffice((s) => s.busy.it);
  const [editing, setEditing] = useState(false);
  const [repo, setRepo] = useState(project.repo ?? "");
  const [branch, setBranch] = useState(project.base_branch ?? "");
  const [saving, setSaving] = useState(false);
  useEffect(() => { setRepo(project.repo ?? ""); setBranch(project.base_branch ?? ""); setEditing(false); }, [project.id, project.repo, project.base_branch]);

  const invalid = repo.trim() !== "" && !REPO_RE.test(repo.trim());
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (invalid) return;
    setSaving(true);
    const ok = await updateProject(project.id, { repo: repo.trim(), base_branch: branch.trim() });
    setSaving(false);
    if (ok) setEditing(false);
  }

  if (editing) {
    return (
      <form onSubmit={save} className="panel space-y-2 p-2">
        <input className="field" placeholder="owner/nama-repo (kosongkan untuk melepas)" value={repo}
          onChange={(e) => setRepo(e.target.value)} aria-invalid={invalid} autoFocus />
        <input className="field" placeholder="branch dasar (default: branch utama repo)" value={branch}
          onChange={(e) => setBranch(e.target.value)} />
        {invalid && <p className="font-term text-[15px] text-neon-red">Format harus owner/nama, mis. aetheriin/toko-online</p>}
        <div className="flex gap-2">
          <button type="submit" disabled={saving || invalid} className="btn flex-1 border-neon-green text-neon-green hover:bg-neon-green/10">
            {saving ? "Mengecek akses..." : "Simpan"}
          </button>
          <button type="button" onClick={() => setEditing(false)} className="btn border-night-600 text-white/60">Batal</button>
        </div>
      </form>
    );
  }

  return (
    <div className="font-term flex items-center justify-between gap-2 text-[16px] leading-5">
      <span className="min-w-0 truncate text-white/70">
        {project.repo ? (
          <>
            GitHub:{" "}
            <a href={`https://github.com/${project.repo}`} target="_blank" rel="noopener noreferrer" className="text-neon-cyan hover:underline">
              {project.repo}
            </a>
            <span className="text-white/40"> ({project.base_branch || "branch utama"})</span>
            {github && !github.configured && <span className="block text-neon-orange">GITHUB_TOKEN belum diatur: PR nonaktif</span>}
            {github?.error && <span className="block text-neon-red">{github.error}</span>}
          </>
        ) : (
          <span className="text-white/40">Belum terhubung ke repo GitHub (hasil hanya disimpan di sini)</span>
        )}
      </span>
      <button type="button" onClick={() => setEditing(true)} disabled={busy}
        className="font-pixel shrink-0 text-[8px] text-neon-cyan hover:underline disabled:opacity-40">
        {project.repo ? "UBAH" : "HUBUNGKAN"}
      </button>
    </div>
  );
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
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("");
  const [saving, setSaving] = useState(false);
  const current = projects.find((p) => p.id === projectId);
  const repoInvalid = repo.trim() !== "" && !REPO_RE.test(repo.trim());

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2 || repoInvalid) return;
    setSaving(true);
    const ok = await createProject({
      name: name.trim(), description: desc.trim(),
      ...(repo.trim() ? { repo: repo.trim() } : {}), ...(branch.trim() ? { base_branch: branch.trim() } : {}),
    });
    setSaving(false);
    if (ok) { setAdding(false); setName(""); setDesc(""); setRepo(""); setBranch(""); }
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
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.runs}){p.repo ? " ⎇" : ""}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => setAdding(!adding)} disabled={busy}
          className="btn h-[38px] border-neon-green/60 text-neon-green hover:bg-neon-green/10" aria-expanded={adding}>
          {adding ? "Batal" : "+ Baru"}
        </button>
      </div>

      {adding && (
        <form onSubmit={submit} className="panel space-y-2 p-2">
          <input className="field" placeholder="Nama proyek (mis. Toko Online)" maxLength={120} value={name}
            onChange={(e) => setName(e.target.value)} autoFocus />
          <input className="field" placeholder="Deskripsi singkat (opsional)" maxLength={4000} value={desc}
            onChange={(e) => setDesc(e.target.value)} />
          <input className="field" placeholder="Repo GitHub owner/nama (opsional, boleh repo kosong)" value={repo}
            onChange={(e) => setRepo(e.target.value)} aria-invalid={repoInvalid} />
          {repo.trim() && (
            <input className="field" placeholder="Branch dasar (default: branch utama repo)" value={branch}
              onChange={(e) => setBranch(e.target.value)} />
          )}
          {repoInvalid && <p className="font-term text-[15px] text-neon-red">Format harus owner/nama, mis. aetheriin/toko-online</p>}
          <button type="submit" disabled={saving || name.trim().length < 2 || repoInvalid}
            className="btn w-full border-neon-green text-neon-green hover:bg-neon-green/10">
            {saving ? (repo.trim() ? "Mengecek akses repo..." : "Menyimpan...") : "Buat Proyek"}
          </button>
        </form>
      )}

      {current && !adding && <RepoLine project={current} />}

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
                    <PrBadge run={r} />
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
