"use client";

import { useState } from "react";
import { useOffice } from "@/lib/store";
import type { ScreenerRow } from "@/lib/types";
import { fmtNum } from "./PlanCard";

const LIQ_COLOR: Record<string, string> = { ok: "#4dff7c", thin: "#ff8a2a", illiquid: "#ff4d5e" };

function Candidate({ row, rank, onDebate, busy }: { row: ScreenerRow; rank?: number; onDebate: () => void; busy: boolean }) {
  const buy = row.status === "BUY";
  return (
    <li className={`panel p-2 ${buy ? "shadow-neon" : ""}`} style={{ borderColor: buy ? "#4dff7c88" : "#ff8a2a55" }}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-pixel text-[11px]" style={{ color: buy ? "#4dff7c" : "#ff8a2a" }}>
          {rank ? `#${rank} ` : ""}{row.symbol}
        </div>
        <div className="font-term text-[15px] text-white/50">
          skor {row.score} · {row.structure ?? ""}{row.liquidity && <span style={{ color: LIQ_COLOR[row.liquidity] }}> · likuid {row.liquidity}</span>}
        </div>
      </div>
      {buy ? (
        <div className="font-term mt-1 grid grid-cols-2 gap-x-3 text-[17px] leading-5">
          <span className="text-white/60">Beli di</span><span className="text-right text-neon-cyan">{fmtNum(row.entry)}</span>
          <span className="text-white/60">Stop loss</span><span className="text-right text-neon-red">{fmtNum(row.stop_loss)}</span>
          <span className="text-white/60">TP1 / TP2</span>
          <span className="text-right text-neon-green">{fmtNum(row.tp1)} / {fmtNum(row.tp2)}</span>
          <span className="text-white/60">RR · ukuran</span>
          <span className="text-right text-white/85">1:{row.rr_tp2} · {fmtNum(row.position.quantity, 0)} lot</span>
        </div>
      ) : (
        <p className="font-term mt-1 text-[16px] leading-5 text-white/70">Harga {fmtNum(row.price)} · {row.reasons[0]}</p>
      )}
      <ul className="font-term mt-1 list-inside list-disc text-[15px] leading-[18px] text-white/55">
        {row.evidence.slice(0, 3).map((e) => <li key={e}>{e}</li>)}
      </ul>
      {row.warnings.length > 0 && <p className="font-term text-[15px] text-neon-orange">⚠ {row.warnings[0]}</p>}
      <button onClick={onDebate} disabled={busy} className="btn mt-1 w-full border-neon-orange/60 text-neon-orange hover:bg-neon-orange/10">
        Debat-kan {row.symbol} (Bull vs Bear + berita)
      </button>
    </li>
  );
}

/** Scan many IDX stocks and list the ones that pass every Risk Agent rule. */
export function ScreenerPanel({ onDebate }: { onDebate: (symbol: string, interval: string) => void }) {
  const { result, progress, universe } = useOffice((s) => s.screener);
  const runScreener = useOffice((s) => s.runScreener);
  const saveUniverse = useOffice((s) => s.saveUniverse);
  const busy = useOffice((s) => s.busy.screener || s.busy.trade);
  const connected = useOffice((s) => s.connected);
  const [interval, setInterval] = useState("1d");
  const [capital, setCapital] = useState("10000000");
  const [riskPct, setRiskPct] = useState("1");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const pct = progress && progress.total ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div className="space-y-3">
      <p className="font-term text-[16px] leading-5 text-white/60">
        Screener memindai daftar saham dengan aturan yang sama seperti Risk Agent, lalu mengurutkan saham yang
        <span className="text-neon-green"> layak beli</span> lengkap dengan harga beli, SL, dan target.
      </p>

      <div className="grid grid-cols-3 gap-2">
        <label>
          <span className="font-pixel text-[8px] text-white/60">TIMEFRAME</span>
          <select className="field" value={interval} onChange={(e) => setInterval(e.target.value)}>
            {["1d", "1h", "30m", "15m"].map((i) => <option key={i}>{i}</option>)}
          </select>
        </label>
        <label>
          <span className="font-pixel text-[8px] text-white/60">MODAL (IDR)</span>
          <input className="field" inputMode="numeric" value={capital} onChange={(e) => setCapital(e.target.value.replace(/[^\d]/g, ""))} />
        </label>
        <label>
          <span className="font-pixel text-[8px] text-white/60">RISIKO %</span>
          <input className="field" inputMode="decimal" value={riskPct} onChange={(e) => setRiskPct(e.target.value.replace(/[^\d.]/g, ""))} />
        </label>
      </div>

      <div className="font-term flex items-center justify-between text-[16px] text-white/60">
        <span>Daftar pindai: {universe.length} saham</span>
        <button onClick={() => { setDraft(universe.join(" ")); setEditing(!editing); }} className="font-pixel text-[8px] text-neon-cyan hover:underline">
          {editing ? "TUTUP" : "UBAH DAFTAR"}
        </button>
      </div>
      {editing && (
        <div className="space-y-2">
          <textarea className="field min-h-[90px]" value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder="Kode saham dipisah spasi/koma, mis. BBCA BUVA BUMI" />
          <button onClick={async () => {
            const symbols = draft.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
            if (await saveUniverse(symbols)) setEditing(false);
          }} className="btn w-full border-neon-green text-neon-green hover:bg-neon-green/10">Simpan daftar</button>
        </div>
      )}

      <button disabled={busy || !connected || universe.length === 0}
        onClick={() => void runScreener({ interval, capital: Number(capital) || undefined, risk_pct: Number(riskPct) || undefined })}
        className="btn w-full border-neon-green text-neon-green hover:bg-neon-green/10">
        {progress ? `Memindai... ${progress.stage === "download" ? "mengunduh data" : `${progress.done}/${progress.total}`}` : "Cari Saham Layak Beli"}
      </button>
      {progress && (
        <div className="h-1.5 overflow-hidden rounded-sm bg-night-700" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className={`h-full bg-neon-green ${progress.stage === "download" ? "w-1/4 animate-pulse" : ""}`}
            style={progress.stage === "download" ? undefined : { width: `${pct}%` }} />
        </div>
      )}

      {result && (
        <div className="space-y-2">
          <div className="font-term text-[16px] text-white/55">
            {new Date(result.created_at).toLocaleString("id-ID")} · {result.interval} · {result.scanned}/{result.universe} dipindai
            {Object.keys(result.errors).length > 0 && (
              <span className="text-neon-orange"> · {Object.keys(result.errors).length} gagal: {Object.keys(result.errors).slice(0, 6).join(", ")}</span>
            )}
          </div>
          {result.demo && <div className="font-term rounded-sm border border-neon-red/60 bg-neon-red/10 px-2 text-neon-red">DATA SINTETIS (demo): jangan dieksekusi.</div>}

          <div className="font-pixel text-[9px] text-neon-green">REKOMENDASI BELI ({result.recommendations.length})</div>
          {result.recommendations.length === 0 ? (
            <p className="font-term text-[16px] text-white/60">
              Tidak ada saham yang lolos semua aturan saat ini, jadi WAIT. Ini wajar: Risk Agent menolak beli tepat di bawah
              resistance, saat data basi, atau saham tidak likuid.
            </p>
          ) : (
            <ol className="space-y-2">
              {result.recommendations.map((r, i) => (
                <Candidate key={r.symbol} row={r} rank={i + 1} busy={busy} onDebate={() => onDebate(r.symbol, result.interval)} />
              ))}
            </ol>
          )}
          {result.journaled && result.journaled.length > 0 && (
            <p className="font-term text-[15px] text-neon-cyan">📓 {result.journaled.join(", ")} dicatat di Jurnal untuk mengukur akurasi screener.</p>
          )}

          {result.watch.length > 0 && (
            <details className="space-y-2">
              <summary className="font-pixel cursor-pointer text-[9px] text-neon-orange">PANTAU: BULLISH TAPI BELUM LOLOS ({result.watch.length})</summary>
              <ul className="mt-2 space-y-2">
                {result.watch.map((r) => <Candidate key={r.symbol} row={r} busy={busy} onDebate={() => onDebate(r.symbol, result.interval)} />)}
              </ul>
            </details>
          )}
          {result.avoid.length > 0 && (
            <p className="font-term text-[16px] text-neon-red">Hindari (tren turun): {result.avoid.join(", ")}</p>
          )}
          <p className="font-term text-[14px] text-white/35">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
