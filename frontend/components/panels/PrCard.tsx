"use client";

import { useOffice } from "@/lib/store";

const STYLE = {
  pending: { color: "#9aa6c2", title: "MEMBUKA PULL REQUEST..." },
  opened: { color: "#4dff7c", title: "PULL REQUEST DIBUKA" },
  draft: { color: "#5fe6ff", title: "PULL REQUEST (DRAFT)" },
  skipped: { color: "#ff8a2a", title: "PR TIDAK DIBUAT" },
  failed: { color: "#ff4d5e", title: "PR GAGAL" },
} as const;

/** Result of the sprint's GitHub pull request (live, or from history). */
export function PrCard() {
  const pr = useOffice((s) => s.pr);
  if (!pr || pr.status === "none") return null;
  const st = STYLE[pr.status];

  return (
    <div className="panel p-3" style={{ borderColor: `${st.color}99` }} role="status">
      <div className={`font-pixel text-[9px] ${pr.status === "pending" ? "animate-pulse" : ""}`} style={{ color: st.color }}>
        {st.title}
      </div>
      <div className="font-term mt-1 text-[17px] leading-5 text-white/80">
        {pr.url ? (
          <>
            <a href={pr.url} target="_blank" rel="noopener noreferrer" className="text-neon-cyan hover:underline">
              PR #{pr.number} di GitHub ↗
            </a>
            {pr.branch && <span className="block text-white/45">branch {pr.branch}</span>}
            <span className="block text-white/55">
              {pr.status === "draft"
                ? "Draft karena QA belum PASS atau ada temuan high. Review lalu tandai Ready for review."
                : "Review perubahannya, lalu merge kalau sudah sesuai."}
            </span>
          </>
        ) : pr.status === "pending" ? (
          <span className="text-white/55">Agen sedang bekerja; PR dibuka setelah QA selesai.</span>
        ) : (
          <span>{pr.error}</span>
        )}
      </div>
    </div>
  );
}
