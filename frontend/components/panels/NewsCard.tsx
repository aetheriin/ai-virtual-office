import type { NewsSentiment } from "@/lib/types";

const LABEL = {
  bullish: { text: "BULLISH", color: "#4dff7c" },
  bearish: { text: "BEARISH", color: "#ff4d5e" },
  neutral: { text: "NETRAL", color: "#ff8a2a" },
  no_data: { text: "TIDAK ADA DATA", color: "#7b8aa8" },
} as const;

const METHOD = { alphavantage: "AV", llm: "AI", lexicon: "KW" } as const;

function ago(iso: string) {
  const h = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
  return h < 48 ? `${Math.round(h)}j` : `${Math.round(h / 24)}h`;
}

/** Sentiment gauge (-1..+1) + top headlines, shown live during the debate and inside the plan. */
export function NewsCard({ news, compact = false }: { news: NewsSentiment; compact?: boolean }) {
  const l = LABEL[news.label];
  const pos = ((news.score + 1) / 2) * 100;
  const items = news.headlines.slice(0, compact ? 4 : 8);

  return (
    <div className={compact ? "" : "panel p-3"}>
      <div className="flex items-center justify-between">
        <div className="font-pixel text-[9px] text-white">SENTIMEN BERITA</div>
        <div className="font-pixel text-[9px]" style={{ color: l.color, textShadow: `0 0 6px ${l.color}` }}>
          {l.text} {news.label !== "no_data" && `${news.score >= 0 ? "+" : ""}${news.score.toFixed(2)}`}
        </div>
      </div>

      <div className="relative mt-2 h-2 rounded-sm" style={{ background: "linear-gradient(90deg,#ff4d5e,#3a4560 50%,#4dff7c)" }}
        role="meter" aria-valuemin={-1} aria-valuemax={1} aria-valuenow={news.score} aria-label="Skor sentimen berita">
        {news.label !== "no_data" && (
          <div className="absolute -top-1 h-4 w-1 -translate-x-1/2 rounded-sm bg-white shadow-[0_0_6px_#fff]" style={{ left: `${pos}%` }} />
        )}
      </div>

      <div className="font-term mt-1 flex flex-wrap justify-between gap-x-2 text-[15px] text-white/50">
        <span>{news.count} berita relevan</span>
        <span>{news.sources.length ? news.sources.join(" · ") : "sumber tidak terjangkau"}</span>
      </div>

      {news.event_risk && (
        <div className="font-term mt-1 rounded-sm border border-neon-orange/60 bg-neon-orange/10 px-2 py-0.5 text-[16px] text-neon-orange">
          ⚠ Rilis data berdampak tinggi dalam 3 jam terakhir
        </div>
      )}

      {items.length > 0 && (
        <ul className="font-term mt-2 space-y-1 text-[16px] leading-[18px]">
          {items.map((h) => {
            const c = h.score > 0.05 ? "#4dff7c" : h.score < -0.05 ? "#ff4d5e" : "#7b8aa8";
            return (
              <li key={h.title + h.published} className="flex gap-2">
                <span className="mt-[2px] w-10 shrink-0 text-right tabular-nums" style={{ color: c }}>
                  {h.score >= 0 ? "+" : ""}{h.score.toFixed(1)}
                </span>
                <span className="min-w-0 text-white/80">
                  {h.url ? (
                    <a href={h.url} target="_blank" rel="noopener noreferrer" className="hover:text-neon-cyan hover:underline">{h.title}</a>
                  ) : h.title}
                  <span className="block text-[14px] text-white/35">
                    {h.source} · {ago(h.published)} · {METHOD[h.method]}{h.high_impact ? " · HIGH IMPACT" : ""}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {news.label === "no_data" && (
        <p className="font-term mt-2 text-[15px] text-white/45">
          Tidak ada berita relevan. Isi ALPHA_VANTAGE_API_KEY / FINNHUB_API_KEY atau cek NEWS_RSS_FEEDS di .env.
        </p>
      )}
    </div>
  );
}
