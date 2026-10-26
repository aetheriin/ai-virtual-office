"use client";

import { useState } from "react";
import { useOffice } from "@/lib/store";
import { NewsCard } from "./NewsCard";
import { PlanCard } from "./PlanCard";

const INTERVALS = ["5m", "15m", "30m", "1h", "1d"];
const SYMBOL_RE = /^[A-Za-z0-9./=-]{2,15}$/;

/** Quick-analysis buttons; the list is editable and stored on the backend. */
function Watchlist({ onPick, disabled }: { onPick: (s: string) => void; disabled: boolean }) {
  const watchlist = useOffice((s) => s.watchlist);
  const save = useOffice((s) => s.saveWatchlist);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [input, setInput] = useState("");

  function add() {
    const items = input.split(/[\s,]+/).map((x) => x.trim().toUpperCase().replace(/\.JK$/, "")).filter(Boolean);
    const valid = items.filter((x) => SYMBOL_RE.test(x));
    setDraft([...new Set([...draft, ...valid])].slice(0, 30));
    setInput("");
  }

  if (editing) {
    return (
      <div className="panel space-y-2 p-2">
        <div className="flex flex-wrap gap-1.5">
          {draft.map((q) => (
            <span key={q} className="font-pixel flex items-center gap-1 rounded-sm border border-neon-green/40 px-2 py-1 text-[9px] text-neon-green">
              {q}
              <button onClick={() => setDraft(draft.filter((x) => x !== q))} aria-label={`Hapus ${q}`} className="text-white/50 hover:text-neon-red">✕</button>
            </span>
          ))}
          {draft.length === 0 && <span className="font-term text-white/40">Watchlist kosong</span>}
        </div>
        <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <input className="field" placeholder="Tambah kode, mis. BUVA BUMI XAUUSD" value={input} onChange={(e) => setInput(e.target.value)} />
          <button type="submit" className="btn border-neon-green/60 text-neon-green">+</button>
        </form>
        <div className="flex gap-2">
          <button onClick={async () => { if (await save(draft)) setEditing(false); }} className="btn flex-1 border-neon-green text-neon-green hover:bg-neon-green/10">Simpan</button>
          <button onClick={() => setEditing(false)} className="btn border-night-600 text-white/60">Batal</button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {watchlist.map((q) => (
        <button key={q} disabled={disabled} onClick={() => onPick(q)} className="btn border-neon-green/50 text-neon-green hover:bg-neon-green/10">
          {q}
        </button>
      ))}
      <button onClick={() => { setDraft(watchlist); setEditing(true); }} className="font-pixel px-1 text-[8px] text-neon-cyan hover:underline">
        ATUR WATCHLIST
      </button>
    </div>
  );
}

/** Single-instrument analysis: Bull vs Bear vs Risk. */
export function TradePanel() {
  const analyze = useOffice((s) => s.analyze);
  const busy = useOffice((s) => s.busy.trade || s.busy.screener);
  const connected = useOffice((s) => s.connected);
  const plan = useOffice((s) => s.plan);
  const news = useOffice((s) => s.news);
  const [symbol, setSymbol] = useState("BBCA");
  const [interval, setInterval] = useState("15m");
  const [capital, setCapital] = useState("10000000");
  const [riskPct, setRiskPct] = useState("1");
  const [ccy, setCcy] = useState("IDR");
  const [formError, setFormError] = useState("");

  function run(sym = symbol) {
    const cap = Number(capital);
    const risk = Number(riskPct);
    if (!/^[A-Za-z0-9./=-]{2,15}$/.test(sym)) return setFormError("Simbol tidak valid");
    if (!(cap > 0)) return setFormError("Modal harus > 0");
    if (!(risk > 0 && risk <= 10)) return setFormError("Risiko per trade 0–10%");
    setFormError("");
    setSymbol(sym.toUpperCase());
    void analyze({ symbol: sym.toUpperCase(), interval, capital: cap, risk_pct: risk, account_currency: ccy });
  }

  return (
    <div className="space-y-3">
      <Watchlist onPick={run} disabled={busy || !connected} />

      <form className="grid grid-cols-2 gap-2" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <label className="col-span-1">
          <span className="font-pixel text-[8px] text-white/60">SIMBOL</span>
          <input className="field uppercase" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="BBCA / XAUUSD" />
        </label>
        <label>
          <span className="font-pixel text-[8px] text-white/60">TIMEFRAME</span>
          <select className="field" value={interval} onChange={(e) => setInterval(e.target.value)}>
            {INTERVALS.map((i) => <option key={i}>{i}</option>)}
          </select>
        </label>
        <label>
          <span className="font-pixel text-[8px] text-white/60">MODAL</span>
          <div className="flex gap-1">
            <select className="field !w-20" value={ccy} onChange={(e) => setCcy(e.target.value)}>
              <option>IDR</option><option>USD</option>
            </select>
            <input className="field" inputMode="numeric" value={capital} onChange={(e) => setCapital(e.target.value.replace(/[^\d.]/g, ""))} />
          </div>
        </label>
        <label>
          <span className="font-pixel text-[8px] text-white/60">RISIKO / TRADE %</span>
          <input className="field" inputMode="decimal" value={riskPct} onChange={(e) => setRiskPct(e.target.value.replace(/[^\d.]/g, ""))} />
        </label>
        {formError && <p className="font-term col-span-2 text-neon-red" role="alert">{formError}</p>}
        <button type="submit" disabled={busy || !connected}
          className="btn col-span-2 border-neon-orange text-neon-orange hover:bg-neon-orange/10">
          {busy ? "Arena sedang sibuk..." : "Mulai Debat"}
        </button>
      </form>

      {!plan && news && <NewsCard news={news} />}
      {plan ? <PlanCard plan={plan} /> : (
        <div className="panel font-term p-4 text-center text-lg text-white/50">
          {busy ? "Risk Agent menunggu argumen Bull & Bear..." : "Pilih simbol untuk memunculkan kartu Trading Plan."}
        </div>
      )}
    </div>
  );
}
