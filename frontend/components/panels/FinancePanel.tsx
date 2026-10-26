"use client";

import { useState } from "react";
import { useOffice } from "@/lib/store";
import { JournalPanel } from "./JournalPanel";
import { ScreenerPanel } from "./ScreenerPanel";
import { TradePanel } from "./TradePanel";

type Sub = "analisa" | "screener" | "jurnal";
const LABEL: Record<Sub, string> = { analisa: "ANALISA", screener: "SCREENER", jurnal: "JURNAL" };

/** Departemen Investasi: single analysis, multi-stock screener and the paper-trading journal. */
export function FinancePanel() {
  const [sub, setSub] = useState<Sub>("analisa");
  const analyze = useOffice((s) => s.analyze);
  const openTrades = useOffice((s) => s.journal.stats?.open ?? 0);

  function debate(symbol: string, interval: string) {
    setSub("analisa");
    void analyze({ symbol, interval, account_currency: "IDR" });
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1" role="tablist">
        {(Object.keys(LABEL) as Sub[]).map((k) => (
          <button key={k} role="tab" aria-selected={sub === k} onClick={() => setSub(k)}
            className={`font-pixel flex-1 rounded-sm border px-2 py-1.5 text-[8px] ${sub === k ? "border-neon-cyan bg-neon-cyan/10 text-neon-cyan" : "border-night-600 text-white/50 hover:text-white/80"}`}>
            {LABEL[k]}{k === "jurnal" && openTrades > 0 ? ` (${openTrades})` : ""}
          </button>
        ))}
      </div>
      {sub === "analisa" && <TradePanel />}
      {sub === "screener" && <ScreenerPanel onDebate={debate} />}
      {sub === "jurnal" && <JournalPanel />}
    </div>
  );
}
