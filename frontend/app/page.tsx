"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { ItPanel } from "@/components/panels/ItPanel";
import { LogFeed } from "@/components/panels/LogFeed";
import { TradePanel } from "@/components/panels/TradePanel";
import type { Dept } from "@/lib/agents";
import { connectOffice, useOffice } from "@/lib/store";

const OfficeScene = dynamic(() => import("@/components/office/OfficeScene"), {
  ssr: false,
  loading: () => <div className="font-pixel absolute inset-0 grid place-items-center text-xs text-neon-green">MEMUAT KANTOR VIRTUAL...</div>,
});

function Chip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`font-pixel flex items-center gap-1.5 rounded-sm border px-2 py-1 text-[8px] ${ok ? "border-neon-green/50 text-neon-green" : "border-neon-orange/50 text-neon-orange"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-neon-green" : "bg-neon-orange"} ${ok ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

export default function Home() {
  const connected = useOffice((s) => s.connected);
  const llm = useOffice((s) => s.llmEnabled);
  const error = useOffice((s) => s.error);
  const clearError = useOffice((s) => s.clearError);
  const focus = useOffice((s) => s.focus);
  const setFocus = useOffice((s) => s.setFocus);
  const [tab, setTab] = useState<Dept>("trade");
  const [panelOpen, setPanelOpen] = useState(true);

  useEffect(() => { connectOffice(); }, []);
  useEffect(() => { if (focus) setTab(focus); }, [focus]);

  return (
    <main className="relative h-dvh w-full overflow-hidden">
      <OfficeScene />

      {/* top bar */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-30 flex flex-wrap items-center justify-between gap-2 bg-gradient-to-b from-night-950 via-night-950/80 to-transparent px-4 pb-6 pt-3">
        <h1 className="font-pixel text-[13px] text-neon-green sm:text-xl" style={{ textShadow: "0 0 10px #4dff7c88" }}>
          RUANG DEBAT - INTRADAY ARENA
        </h1>
        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5">
          <Chip ok={connected} label={connected ? "BACKEND ONLINE" : "BACKEND OFFLINE"} />
          <Chip ok={llm} label={llm ? "LLM AKTIF" : "RULE ENGINE"} />
          {(["all", "it", "trade"] as const).map((f) => (
            <button key={f} onClick={() => setFocus(f === "all" ? null : f)}
              className={`btn ${((focus ?? "all") === f) ? "border-neon-cyan bg-neon-cyan/10 text-neon-cyan" : "border-night-600 text-white/60 hover:text-white"}`}>
              {f === "all" ? "Semua" : f === "it" ? "Ruang IT" : "Ruang Trading"}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div role="alert" className="font-term absolute left-1/2 top-16 z-30 flex -translate-x-1/2 items-center gap-3 rounded-sm border border-neon-red bg-night-950/95 px-3 py-2 text-lg text-neon-red">
          {error}
          <button onClick={clearError} className="text-white/60 hover:text-white" aria-label="Tutup">✕</button>
        </div>
      )}

      {/* side panel (bottom sheet on phones) */}
      <aside className={`absolute z-30 flex flex-col transition-transform duration-300
        inset-x-0 bottom-0 max-h-[50dvh] sm:inset-x-auto sm:bottom-4 sm:right-4 sm:top-20 sm:max-h-none sm:w-[400px]
        ${panelOpen ? "translate-y-0 sm:translate-x-0" : "translate-y-[calc(100%-44px)] sm:translate-y-0 sm:translate-x-[calc(100%+16px)]"}`}>
        <div className="panel flex min-h-0 flex-1 flex-col">
          <div className="flex items-center border-b border-night-600">
            {(["trade", "it"] as const).map((t) => (
              <button key={t} onClick={() => { setTab(t); setPanelOpen(true); }}
                className={`font-pixel flex-1 px-2 py-3 text-[9px] ${tab === t ? "text-neon-green" : "text-white/40 hover:text-white/70"}`}
                style={tab === t ? { boxShadow: "inset 0 -2px 0 #4dff7c" } : undefined}>
                {t === "trade" ? "DEPT. INVESTASI" : "DEPT. IT"}
              </button>
            ))}
            <button onClick={() => setPanelOpen(!panelOpen)} className="px-3 text-white/50 hover:text-white" aria-label={panelOpen ? "Tutup panel" : "Buka panel"}>
              {panelOpen ? "—" : "+"}
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">{tab === "trade" ? <TradePanel /> : <ItPanel />}</div>
        </div>
      </aside>

      {/* agent log */}
      <div className="pointer-events-none absolute bottom-4 left-4 right-4 z-20 hidden sm:block sm:right-auto">
        <LogFeed />
      </div>
    </main>
  );
}
