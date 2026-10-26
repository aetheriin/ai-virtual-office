"use client";

import { useState } from "react";
import { useOffice } from "@/lib/store";
import { PlanCard } from "./PlanCard";

const QUICK = ["BBCA", "BBRI", "TLKM", "XAUUSD", "EURUSD", "USDJPY"];
const INTERVALS = ["5m", "15m", "30m", "1h", "1d"];

export function TradePanel() {
  const analyze = useOffice((s) => s.analyze);
  const busy = useOffice((s) => s.busy.trade);
  const connected = useOffice((s) => s.connected);
  const plan = useOffice((s) => s.plan);
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
      <div className="flex flex-wrap gap-1.5">
        {QUICK.map((q) => (
          <button key={q} disabled={busy || !connected} onClick={() => run(q)}
            className="btn border-neon-green/50 text-neon-green hover:bg-neon-green/10">
            Analisa {q}
          </button>
        ))}
      </div>

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
          {busy ? "Bull vs Bear sedang berdebat..." : "Mulai Debat"}
        </button>
      </form>

      {plan ? <PlanCard plan={plan} /> : (
        <div className="panel font-term p-4 text-center text-lg text-white/50">
          {busy ? "Risk Agent menunggu argumen Bull & Bear..." : "Pilih simbol untuk memunculkan kartu Trading Plan."}
        </div>
      )}
    </div>
  );
}
