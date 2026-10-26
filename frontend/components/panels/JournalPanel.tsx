"use client";

import { useOffice } from "@/lib/store";
import type { PaperTrade } from "@/lib/types";
import { fmtNum } from "./PlanCard";

const RESULT = {
  tp2: { label: "TP2 ✓", color: "#4dff7c" },
  tp1_be: { label: "TP1 + BE", color: "#9bff3a" },
  sl: { label: "SL ✕", color: "#ff4d5e" },
  expired: { label: "kedaluwarsa", color: "#9aa6c2" },
} as const;

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-sm border border-night-600 bg-night-950 px-2 py-1">
      <div className="font-pixel text-[7px] text-white/50">{label}</div>
      <div className="font-term text-xl tabular-nums" style={{ color }}>{value}</div>
    </div>
  );
}

function Row({ t, onDelete }: { t: PaperTrade; onDelete: () => void }) {
  const r = t.result ? RESULT[t.result] : null;
  const status = r ? r.label : t.status === "tp1" ? "TP1 kena, sisa jalan" : "terbuka";
  const color = r?.color ?? (t.status === "tp1" ? "#9bff3a" : "#5fe6ff");
  return (
    <li className="font-term flex items-start justify-between gap-2 border-b border-white/5 py-1 text-[16px] leading-5">
      <span className="min-w-0">
        <span className={t.side === "LONG" ? "text-neon-green" : "text-neon-red"}>{t.side === "LONG" ? "BELI" : "JUAL"}</span>{" "}
        <span className="text-white">{t.symbol}</span> @ {fmtNum(t.entry)}
        <span className="block text-[14px] text-white/40">
          {new Date(t.opened_at).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })} · {t.interval} · {t.source}
          {" "}· SL {fmtNum(t.stop_loss)} · TP {fmtNum(t.tp1)}/{fmtNum(t.tp2)}
        </span>
      </span>
      <span className="shrink-0 text-right">
        <span style={{ color }}>{status}</span>
        {t.r_multiple !== null && <span className="block tabular-nums" style={{ color }}>{t.r_multiple > 0 ? "+" : ""}{t.r_multiple}R</span>}
        <button onClick={onDelete} className="ml-auto block text-[13px] text-white/30 hover:text-neon-red" aria-label={`Hapus trade ${t.symbol}`}>hapus</button>
      </span>
    </li>
  );
}

/** Paper-trading journal: how the plans would have played out, without risking money. */
export function JournalPanel() {
  const { stats, trades, loading } = useOffice((s) => s.journal);
  const loadJournal = useOffice((s) => s.loadJournal);
  const deleteTrade = useOffice((s) => s.deleteTrade);

  return (
    <div className="space-y-3">
      <p className="font-term text-[16px] leading-5 text-white/60">
        Setiap plan BUY/SELL (dari Analisa dan 3 teratas Screener) dicatat sebagai trade kertas, lalu dicek otomatis tiap 15 menit:
        separuh posisi keluar di TP1, sisanya di TP2 dengan stop pindah ke harga beli.
      </p>
      {stats && (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="TERTUTUP" value={`${stats.closed}`} />
            <Stat label="WIN RATE" value={stats.win_rate === null ? "-" : `${Math.round(stats.win_rate * 100)}%`}
              color={stats.win_rate !== null && stats.win_rate >= 0.5 ? "#4dff7c" : undefined} />
            <Stat label="RATA-RATA" value={stats.avg_r === null ? "-" : `${stats.avg_r > 0 ? "+" : ""}${stats.avg_r}R`}
              color={stats.avg_r !== null ? (stats.avg_r > 0 ? "#4dff7c" : "#ff4d5e") : undefined} />
            <Stat label="TOTAL R" value={`${stats.total_r > 0 ? "+" : ""}${stats.total_r}R`} color={stats.total_r >= 0 ? "#4dff7c" : "#ff4d5e"} />
            <Stat label="P/L KERTAS" value={`Rp${fmtNum(stats.paper_pnl, 0)}`} color={stats.paper_pnl >= 0 ? "#4dff7c" : "#ff4d5e"} />
            <Stat label="TERBUKA" value={`${stats.open}`} color="#5fe6ff" />
          </div>
          {stats.note && <p className="font-term text-[15px] text-neon-orange">{stats.note}</p>}
        </>
      )}
      <button onClick={() => void loadJournal(true)} disabled={loading} className="btn w-full border-neon-cyan text-neon-cyan hover:bg-neon-cyan/10">
        {loading ? "Mengecek harga..." : "Cek hasil sekarang"}
      </button>
      {trades.length === 0 ? (
        <p className="font-term text-[16px] text-white/45">Belum ada trade. Jalankan Analisa atau Screener; plan BUY/SELL otomatis masuk ke sini.</p>
      ) : (
        <ul>{trades.map((t) => <Row key={t.id} t={t} onDelete={() => void deleteTrade(t.id)} />)}</ul>
      )}
    </div>
  );
}
