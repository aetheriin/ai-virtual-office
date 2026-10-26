import type { Candle } from "@/lib/types";

/** Candlestick mini chart with entry / SL / TP lines. Pure SVG, no chart lib. */
export function MiniChart({ candles, levels }: {
  candles: Candle[];
  levels?: { label: string; value: number; color: string }[];
}) {
  const W = 340;
  const H = 130;
  const data = candles.slice(-60);
  if (data.length < 2) return null;
  const vals = [...data.flatMap((c) => [c.h, c.l]), ...(levels ?? []).map((l) => l.value)];
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const y = (v: number) => H - 6 - ((v - min) / (max - min || 1)) * (H - 12);
  const step = (W - 40) / data.length;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Grafik candlestick">
      <rect width={W} height={H} fill="#050a14" />
      {data.map((c, i) => {
        const x = i * step + step / 2;
        const up = c.c >= c.o;
        const col = up ? "#4dff7c" : "#ff4d5e";
        return (
          <g key={i}>
            <line x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} stroke={col} strokeWidth={1} />
            <rect x={x - step * 0.32} width={step * 0.64} y={y(Math.max(c.o, c.c))} height={Math.max(1, Math.abs(y(c.o) - y(c.c)))} fill={col} />
          </g>
        );
      })}
      {levels?.map((l) => (
        <g key={l.label}>
          <line x1={0} x2={W - 40} y1={y(l.value)} y2={y(l.value)} stroke={l.color} strokeDasharray="4 3" strokeWidth={1} />
          <text x={W - 38} y={y(l.value) + 3} fill={l.color} fontSize={9} fontFamily="VT323, monospace">{l.label}</text>
        </g>
      ))}
    </svg>
  );
}
