"""Departemen Investasi — Intraday Arena: Bull vs Bear, judged by Risk (inspired by TauricResearch/TradingAgents).

Pipeline:
    market data -> MarketFacts (deterministic)
    Bull  : evidence score + LONG proposal  (+ LLM narrative)
    Bear  : evidence score + SHORT proposal + 3 biggest risks (+ LLM rebuttal)
    Bull  : short rebuttal round
    Risk  : hard rules (volatility, RR, evidence gap, daily loss) + optional LLM veto -> Trading Plan

The LLM only writes arguments and may downgrade a trade to WAIT; it never invents prices.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from ..config import settings
from ..llm import chat, extract_json
from ..market.data import MarketData
from ..market.indicators import MarketFacts, compute_facts
from ..risk import position_size, round_price, rr

Emit = Callable[[str, dict], Awaitable[None]]

MAX_INTRADAY_ATR_PCT = 3.5   # above this the market is too wild for an intraday plan
MIN_EVIDENCE_GAP = 2.0       # winning side must out-score the other by this much


def fmt(x: float) -> str:
    """Human price format: 9,025 | 2,401.35 | 1.08523"""
    if abs(x) >= 1000:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    if abs(x) >= 10:
        return f"{x:,.2f}"
    return f"{x:.5f}"


@dataclass
class Proposal:
    side: str                # LONG | SHORT
    score: float
    evidence: list[str]
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    trigger: str
    thesis: str = ""
    risks: list[str] = field(default_factory=list)

    @property
    def rr_tp1(self) -> float:
        return rr(self.entry, self.stop_loss, self.tp1)

    @property
    def rr_tp2(self) -> float:
        return rr(self.entry, self.stop_loss, self.tp2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(rr_tp1=round(self.rr_tp1, 2), rr_tp2=round(self.rr_tp2, 2))
        return d


# --------------------------------------------------------------------------- rule engines
def _beyond(entry: float, tp1: float, tp2: float, risk: float, asset: str, *, up: bool) -> tuple[float, float]:
    """Guarantee targets remain on the profitable side of entry after tick rounding."""
    sign = 1 if up else -1
    e = round_price(entry, asset)
    if sign * (round_price(tp1, asset, "down" if up else "up") - e) <= 0:
        tp1 = entry + sign * risk
    if sign * (tp2 - tp1) <= 0:
        tp2 = tp1 + sign * risk
    return tp1, tp2


def bull_case(f: MarketFacts, asset: str) -> Proposal:
    ev: list[tuple[float, str]] = []
    if f.structure == "bullish":
        ev.append((2, "Struktur bullish: Higher High & Higher Low"))
    else:
        if f.higher_highs:
            ev.append((1, "Swing high terbaru lebih tinggi (Higher High)"))
        if f.higher_lows:
            ev.append((1, "Swing low terbaru lebih tinggi (Higher Low)"))
    if f.support_held:
        ev.append((1, f"Support {fmt(f.support)} bertahan 5 candle terakhir"))
    if f.breakout_up:
        ev.append((1.5, f"Breakout: close di atas swing high {fmt(f.swing_highs[-1])}"))
    if f.retest_up:
        ev.append((1, "Breakout + retest level lama berhasil"))
    if f.volume_trend == "rising" and f.change_pct >= 0:
        ev.append((1, f"Volume menguat ({f.volume_ratio:.2f}x rata-rata)"))
    if f.last_close > f.ema20 > f.ema50:
        ev.append((1, "Harga > EMA20 > EMA50"))
    if f.lower_wick_rejection:
        ev.append((1, "Ekor bawah panjang: buyer menolak harga rendah"))

    entry = f.last_close
    stop = min(f.support, f.swing_lows[-1]) - 0.2 * f.atr
    if entry - stop < 0.5 * f.atr:
        stop = entry - f.atr
    risk = entry - stop
    above = sorted(p for p in f.swing_highs if p > entry + 0.1 * f.atr)
    tp1 = above[0] if above else entry + 2 * f.atr
    tp2 = above[1] if len(above) > 1 else entry + 2 * (tp1 - entry)
    if tp2 - entry < 1.5 * risk and not above[1:]:
        tp2 = entry + 2.5 * risk

    tp1, tp2 = _beyond(entry, tp1, tp2, risk, asset, up=True)
    level = f.swing_highs[-1] if not f.breakout_up else f.swing_highs[-2]
    return Proposal(
        side="LONG",
        score=sum(w for w, _ in ev),
        evidence=[t for _, t in ev] or ["Belum ada bukti bullish yang kuat"],
        entry=round_price(entry, asset),
        stop_loss=round_price(stop, asset, "down"),
        tp1=round_price(tp1, asset, "down"),
        tp2=round_price(tp2, asset, "down"),
        trigger=f"Candle {('close bertahan di atas' if f.breakout_up else 'close di atas')} {fmt(level)} dengan volume > rata-rata",
    )


def bear_case(f: MarketFacts, asset: str, bull: Proposal) -> Proposal:
    ev: list[tuple[float, str]] = []
    if f.structure == "bearish":
        ev.append((2, "Struktur bearish: Lower High & Lower Low"))
    else:
        if f.lower_highs:
            ev.append((1, "Swing high terbaru lebih rendah (Lower High)"))
        if f.lower_lows:
            ev.append((1, "Swing low terbaru lebih rendah (Lower Low)"))
    if f.upper_wick_rejection:
        ev.append((1, "Ekor atas panjang: penolakan di harga tinggi"))
    if f.liquidity_grab_up:
        ev.append((1.5, f"Liquidity grab: wick tembus {fmt(f.swing_highs[-1])} lalu close kembali di bawah"))
    if f.breakdown:
        ev.append((1.5, f"Breakdown: close di bawah swing low {fmt(f.swing_lows[-1])}"))
    if f.volume_trend == "falling" and f.change_pct >= 0:
        ev.append((1, f"Kenaikan tanpa volume ({f.volume_ratio:.2f}x) — rawan gagal"))
    if f.volume_trend == "rising" and f.change_pct < 0:
        ev.append((1, "Volume besar saat harga turun (distribusi)"))
    if f.last_close < f.ema20 < f.ema50:
        ev.append((1, "Harga < EMA20 < EMA50"))

    risks: list[str] = []
    if bull.rr_tp1 < settings.min_rr:
        risks.append(f"Resistance terdekat terlalu dekat: RR LONG ke TP1 hanya 1:{bull.rr_tp1:.2f}")
    if f.volume_trend != "rising":
        risks.append(f"Volume tidak mengonfirmasi ({f.volume_trend}, {f.volume_ratio:.2f}x)")
    if f.upper_wick_rejection or f.liquidity_grab_up:
        risks.append("Ada jejak seller agresif di area atas (wick/liquidity grab)")
    if f.atr_pct > 2:
        risks.append(f"Volatilitas tinggi: ATR {f.atr_pct:.2f}% dari harga, SL mudah tersapu")
    if f.structure != "bullish":
        risks.append(f"Struktur pasar belum bullish ({f.structure})")
    if f.last_close < f.ema50:
        risks.append("Harga masih di bawah EMA50")
    risks += ["Risiko berita/makro mendadak di sesi intraday", "Spread & slippage saat entry market"]

    entry = f.last_close
    stop = max(f.resistance, f.swing_highs[-1]) + 0.2 * f.atr
    if stop - entry < 0.5 * f.atr:
        stop = entry + f.atr
    risk = stop - entry
    below = sorted((p for p in f.swing_lows if p < entry - 0.1 * f.atr), reverse=True)
    tp1 = below[0] if below else entry - 2 * f.atr
    tp2 = below[1] if len(below) > 1 else entry - 2 * (entry - tp1)
    if entry - tp2 < 1.5 * risk and not below[1:]:
        tp2 = entry - 2.5 * risk

    tp1, tp2 = _beyond(entry, max(tp1, 0), max(tp2, 0), risk, asset, up=False)
    return Proposal(
        side="SHORT",
        score=sum(w for w, _ in ev),
        evidence=[t for _, t in ev] or ["Belum ada bukti bearish yang kuat"],
        entry=round_price(entry, asset),
        stop_loss=round_price(stop, asset, "up"),
        tp1=round_price(tp1, asset, "up"),
        tp2=round_price(tp2, asset, "up"),
        trigger=f"Candle close di bawah {fmt(f.support)} atau rejection kuat di {fmt(f.resistance)}",
        risks=risks[:3],
    )


def judge(
    f: MarketFacts,
    bull: Proposal,
    bear: Proposal,
    *,
    capital: float,
    risk_pct: float,
    today_loss_pct: float,
    asset: str,
    quote_ccy: str,
    account_ccy: str,
) -> dict:
    """Risk Agent's hard rules. Returns the trading plan dict."""
    reasons: list[str] = []
    status = "WAIT"
    chosen: Proposal | None = None

    gap = bull.score - bear.score
    if today_loss_pct >= settings.max_daily_loss_pct:
        reasons.append(f"VETO: batas rugi harian {settings.max_daily_loss_pct}% sudah tercapai ({today_loss_pct}%)")
    elif f.atr_pct > MAX_INTRADAY_ATR_PCT:
        reasons.append(f"VETO: volatilitas ekstrem (ATR {f.atr_pct:.2f}% > {MAX_INTRADAY_ATR_PCT}%)")
    elif abs(gap) < MIN_EVIDENCE_GAP:
        reasons.append(f"Bukti seimbang (Bull {bull.score:g} vs Bear {bear.score:g}); selisih < {MIN_EVIDENCE_GAP:g}")
    else:
        cand = bull if gap > 0 else bear
        if cand.rr_tp2 < settings.min_rr:
            reasons.append(f"VETO: RR {cand.side} ke TP2 hanya 1:{cand.rr_tp2:.2f} (< 1:{settings.min_rr})")
        elif cand.rr_tp1 < 1.0:
            reasons.append(f"VETO: TP1 {cand.side} terlalu dekat (RR 1:{cand.rr_tp1:.2f})")
        else:
            chosen = cand
            status = "BUY" if cand.side == "LONG" else "SELL"
            reasons.append(f"{cand.side} unggul {abs(gap):g} poin bukti; RR TP1 1:{cand.rr_tp1:.2f}, TP2 1:{cand.rr_tp2:.2f}")

    ref = chosen or (bull if gap >= 0 else bear)
    size = position_size(
        capital=capital, risk_pct=risk_pct, entry=ref.entry, stop=ref.stop_loss,
        asset_class=asset, account_currency=account_ccy, quote_currency=quote_ccy,
    )
    if chosen and size.quantity <= 0:
        status = "WAIT"
        reasons.append(f"VETO: {size.note}")
    return {
        "status": status,
        "bias": ref.side,
        "entry": ref.entry,
        "stop_loss": ref.stop_loss,
        "tp1": ref.tp1,
        "tp2": ref.tp2,
        "rr_tp1": round(ref.rr_tp1, 2),
        "rr_tp2": round(ref.rr_tp2, 2),
        "trigger": ref.trigger,
        "position": asdict(size),
        "capital": capital,
        "risk_pct": risk_pct,
        "scores": {"bull": bull.score, "bear": bear.score},
        "reasons": reasons,
    }


# --------------------------------------------------------------------------- LLM prompts
BULL_SYSTEM = (
    "Kamu adalah BULL AGENT di Intraday Arena. Bangun kasus TERKUAT bahwa harga akan NAIK, "
    "HANYA berdasarkan data JSON yang diberikan (harga, volume, struktur, level). Jangan mengarang angka. "
    "Jawab dalam Bahasa Indonesia, maksimal 2 kalimat tesis, tegas dan percaya diri."
)
BEAR_SYSTEM = (
    "Kamu adalah BEAR AGENT di Intraday Arena, si skeptis. Cari alasan terkuat trade LONG akan GAGAL atau harga TURUN, "
    "dan tantang argumen Bull secara langsung. HANYA pakai data JSON yang diberikan. Bahasa Indonesia, maksimal 3 kalimat."
)
RISK_SYSTEM = (
    "Kamu adalah RISK AGENT, sang hakim dengan HAK VETO. Kamu menerima fakta pasar, argumen Bull & Bear, dan keputusan "
    "aturan keras. Kamu TIDAK BOLEH mengubah angka atau membuka posisi baru; kamu hanya boleh menyetujui keputusan, atau "
    "menurunkannya menjadi WAIT jika bukti kurang. Balas JSON: {\"verdict\": \"APPROVE\"|\"WAIT\", \"summary\": \"<=3 kalimat Bahasa Indonesia\"}."
)


def _facts_brief(md: MarketData, f: MarketFacts) -> str:
    return json.dumps(
        {"symbol": md.instrument.symbol, "interval": md.interval, "data_source": md.source, **f.to_dict()},
        ensure_ascii=False,
    )


def _fallback_bull_thesis(p: Proposal, f: MarketFacts) -> str:
    if p.score == 0:
        return f"Jujur saja, data belum mendukung LONG: struktur {f.structure} dan belum ada breakout. Saya hanya masuk jika {p.trigger.lower()}."
    extra = f", ditambah {len(p.evidence) - 1} konfirmasi lain" if len(p.evidence) > 1 else ""
    return (f"{p.evidence[0]}{extra} — buyer masih memegang kendali. "
            f"Target realistis {fmt(p.tp1)} lalu {fmt(p.tp2)} selama {fmt(p.stop_loss)} tidak jebol.")


def _fallback_bear_thesis(p: Proposal, bull: Proposal) -> str:
    lead = p.evidence[0] if p.score else "Bukti bearish memang tipis, tapi bukti bullish juga belum cukup"
    return f"{lead}. Risiko terbesar LONG: {p.risks[0].lower()}. Tunggu bukti, jangan menebak."


async def run_debate(
    md: MarketData,
    emit: Emit,
    *,
    capital: float | None = None,
    risk_pct: float | None = None,
    today_loss_pct: float = 0.0,
    account_currency: str = "IDR",
) -> dict:
    capital = capital or settings.default_capital
    risk_pct = risk_pct or settings.default_risk_pct
    inst = md.instrument
    f = compute_facts(md.candles)
    brief = _facts_brief(md, f)

    await emit("agent:status", {"agent": "bull", "state": "debating"})
    bull = bull_case(f, inst.asset_class)
    bull.thesis = await chat(
        settings.model_debate, BULL_SYSTEM,
        f"DATA:\n{brief}\n\nBUKTI TERHITUNG:\n{json.dumps(bull.evidence, ensure_ascii=False)}\n"
        f"Usulan LONG: entry {bull.entry}, SL {bull.stop_loss}, TP1 {bull.tp1}, TP2 {bull.tp2}. Tulis tesis naik.",
        temperature=0.7,
    ) or _fallback_bull_thesis(bull, f)
    await emit("agent:message", {"agent": "bull", "kind": "thesis", "text": bull.thesis, "data": bull.to_dict()})

    await emit("agent:status", {"agent": "bear", "state": "debating"})
    bear = bear_case(f, inst.asset_class, bull)
    bear.thesis = await chat(
        settings.model_debate, BEAR_SYSTEM,
        f"DATA:\n{brief}\n\nARGUMEN BULL:\n{bull.thesis}\n\nBUKTI BEARISH:\n{json.dumps(bear.evidence, ensure_ascii=False)}\n"
        f"3 RISIKO:\n{json.dumps(bear.risks, ensure_ascii=False)}\nBantah Bull.",
        temperature=0.7,
    ) or _fallback_bear_thesis(bear, bull)
    await emit("agent:message", {"agent": "bear", "kind": "thesis", "text": bear.thesis, "data": bear.to_dict()})

    rebuttal = await chat(
        settings.model_debate, BULL_SYSTEM,
        f"DATA:\n{brief}\n\nBEAR berkata: {bear.thesis}\nBalas satu kalimat, akui risiko yang valid.",
        temperature=0.7,
    ) or (f"Poin soal '{bear.risks[0].split(':')[0].lower()}' valid — makanya SL saya di {fmt(bull.stop_loss)}, bukan menebak."
          if bull.score else "Oke, tanpa trigger saya tidak akan memaksa LONG.")
    await emit("agent:message", {"agent": "bull", "kind": "rebuttal", "text": rebuttal})
    await emit("agent:status", {"agent": "bull", "state": "idle"})
    await emit("agent:status", {"agent": "bear", "state": "idle"})

    await emit("agent:status", {"agent": "risk", "state": "thinking"})
    plan = judge(
        f, bull, bear, capital=capital, risk_pct=risk_pct, today_loss_pct=today_loss_pct,
        asset=inst.asset_class, quote_ccy=inst.currency, account_ccy=account_currency,
    )
    verdict = extract_json(await chat(
        settings.model_risk, RISK_SYSTEM,
        f"FAKTA:\n{brief}\n\nBULL ({bull.score}): {bull.thesis}\nBEAR ({bear.score}): {bear.thesis}\n"
        f"KEPUTUSAN ATURAN: {json.dumps(plan, ensure_ascii=False)}",
        prefer_gemini=True, temperature=0.2,
    ))
    summary = None
    if isinstance(verdict, dict):
        summary = verdict.get("summary")
        if str(verdict.get("verdict", "")).upper() == "WAIT" and plan["status"] != "WAIT":
            plan["status"] = "WAIT"
            plan["reasons"].append("VETO Risk Agent (LLM): bukti dinilai belum cukup")
    plan["summary"] = summary or " ".join(plan["reasons"])
    plan.update(
        symbol=inst.symbol,
        asset_class=inst.asset_class,
        interval=md.interval,
        price=f.last_close,
        as_of=f.last_time,
        data_source=md.source,
        demo=not md.is_live,
        account_currency=account_currency,
        facts=f.to_dict(),
        bull=bull.to_dict(),
        bear=bear.to_dict(),
    )
    await emit("agent:message", {"agent": "risk", "kind": "verdict", "text": plan["summary"]})
    await emit("agent:status", {"agent": "risk", "state": "idle"})
    return plan
