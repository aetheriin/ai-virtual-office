import type { TradingPlan } from "@/lib/types";
import { useOffice } from "@/lib/store";
import { MiniChart } from "./MiniChart";

const STATUS_STYLE = {
  BUY: { color: "#4dff7c", shadow: "shadow-neon", label: "BUY / LONG" },
  SELL: { color: "#ff4d5e", shadow: "shadow-neon-red", label: "SELL / SHORT" },
  WAIT: { color: "#ff8a2a", shadow: "shadow-neon-orange", label: "WAIT" },
} as const;

export function fmtNum(v: number, digits?: number) {
  const d = digits ?? (Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 10 ? 2 : 5);
  return v.toLocaleString("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: d });
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-white/5 py-0.5">
      <span className="text-white/60">{label}</span>
      <span style={{ color }} className="tabular-nums">{value}</span>
    </div>
  );
}

export function PlanCard({ plan }: { plan: TradingPlan }) {
  const market = useOffice((s) => s.market);
  const st = STATUS_STYLE[plan.status];
  const ccy = plan.account_currency;
  const total = plan.scores.bull + plan.scores.bear || 1;
  const isWait = plan.status === "WAIT";

  return (
    <div className={`panel scanlines p-3 ${st.shadow}`} style={{ borderColor: st.color }}>
      <div className="flex items-center justify-between">
        <div className="font-pixel text-[11px] text-white">TRADING PLAN</div>
        <div className="font-term text-white/60">{plan.symbol} · {plan.interval}</div>
      </div>

      {plan.demo && (
        <div className="font-term mt-2 rounded-sm border border-neon-red/60 bg-neon-red/10 px-2 py-1 text-neon-red">
          DATA SINTETIS (demo) — sumber live tidak terjangkau. JANGAN dieksekusi.
        </div>
      )}

      <div className="mt-2 flex items-center gap-3">
        <div className="font-pixel rounded-sm border-2 px-3 py-2 text-[14px]" style={{ color: st.color, borderColor: st.color, textShadow: `0 0 8px ${st.color}` }}>
          {st.label}
        </div>
        <div className="font-term text-lg leading-5 text-white/80">
          Harga {fmtNum(plan.price)}
          <br />
          <span className="text-white/50">{isWait ? `Bias ${plan.bias} (referensi)` : `Sumber: ${plan.data_source}`}</span>
        </div>
      </div>

      {market && market.symbol === plan.symbol && (
        <div className="mt-2 overflow-hidden rounded-sm border border-night-600">
          <MiniChart
            candles={market.candles}
            levels={[
              { label: "TP2", value: plan.tp2, color: "#9bff3a" },
              { label: "TP1", value: plan.tp1, color: "#4dff7c" },
              { label: "ENTRY", value: plan.entry, color: "#5fe6ff" },
              { label: "SL", value: plan.stop_loss, color: "#ff4d5e" },
            ]}
          />
        </div>
      )}

      <div className={`font-term mt-2 grid grid-cols-1 gap-x-4 text-lg ${isWait ? "opacity-70" : ""}`}>
        <Row label="Entry" value={fmtNum(plan.entry)} color="#5fe6ff" />
        <Row label="Stop Loss" value={fmtNum(plan.stop_loss)} color="#ff4d5e" />
        <Row label="TP 1" value={`${fmtNum(plan.tp1)} (1:${plan.rr_tp1})`} color="#4dff7c" />
        <Row label="TP 2" value={`${fmtNum(plan.tp2)} (1:${plan.rr_tp2})`} color="#9bff3a" />
        <Row label="Ukuran" value={`${fmtNum(plan.position.quantity, 2)} ${plan.position.unit}`} />
        <Row label={`Risiko (${plan.risk_pct}%)`} value={`${ccy} ${fmtNum(plan.position.max_loss, 0)}`} />
      </div>
      {plan.position.note && <p className="font-term mt-1 text-white/50">* {plan.position.note}</p>}

      <div className="mt-3">
        <div className="font-pixel mb-1 flex justify-between text-[8px]">
          <span className="text-neon-green">BULL {plan.scores.bull}</span>
          <span className="text-neon-red">BEAR {plan.scores.bear}</span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-sm bg-night-700">
          <div className="bg-neon-green" style={{ width: `${(plan.scores.bull / total) * 100}%` }} />
          <div className="bg-neon-red" style={{ width: `${(plan.scores.bear / total) * 100}%` }} />
        </div>
      </div>

      <div className="font-term mt-3 space-y-1 text-[17px] leading-5">
        <div className="text-neon-orange">Keputusan Risk Agent</div>
        <p className="text-white/85">{plan.summary}</p>
        <ul className="list-inside list-disc text-white/60">
          {plan.reasons.map((r) => <li key={r}>{r}</li>)}
        </ul>
        <p className="text-white/60"><span className="text-neon-cyan">Trigger:</span> {plan.trigger}</p>
      </div>

      <details className="font-term mt-2 text-[16px] leading-5">
        <summary className="cursor-pointer text-white/70">Argumen Bull & Bear</summary>
        <div className="mt-1 space-y-2">
          <div>
            <div className="text-neon-green">BULL — {plan.bull.thesis}</div>
            <ul className="list-inside list-disc text-white/60">{plan.bull.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
          </div>
          <div>
            <div className="text-neon-red">BEAR — {plan.bear.thesis}</div>
            <div className="text-white/70">3 risiko terbesar:</div>
            <ol className="list-inside list-decimal text-white/60">{plan.bear.risks.map((e) => <li key={e}>{e}</li>)}</ol>
          </div>
        </div>
      </details>
      <p className="font-term mt-2 text-[14px] text-white/35">
        Bukan saran keuangan. Eksekusi manual di MetaTrader/sekuritas setelah verifikasi sendiri.
      </p>
    </div>
  );
}
