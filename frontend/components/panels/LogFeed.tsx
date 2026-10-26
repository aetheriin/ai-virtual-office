"use client";

import { useEffect, useRef, useState } from "react";
import { AGENT_BY_ID } from "@/lib/agents";
import { useOffice } from "@/lib/store";

const COLOR = { cyan: "#5fe6ff", green: "#4dff7c", orange: "#ff8a2a", red: "#ff4d5e" } as const;

export function LogFeed() {
  const messages = useOffice((s) => s.messages);
  const [open, setOpen] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages.length, open]);

  return (
    <div className="panel pointer-events-auto w-full sm:w-[440px]">
      <button onClick={() => setOpen(!open)} className="font-pixel flex w-full items-center justify-between px-3 py-2 text-[9px] text-neon-green">
        <span>LOG AGEN ({messages.length})</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="font-term max-h-40 overflow-y-auto px-3 pb-2 text-[16px] leading-5 sm:max-h-52">
          {messages.length === 0 && <div className="text-white/40">Belum ada aktivitas. Kirim brief atau mulai analisa.</div>}
          {messages.map((m) => {
            const a = AGENT_BY_ID[m.agent];
            return (
              <div key={m.id}>
                <span className="text-white/30">{new Date(m.at).toLocaleTimeString("id-ID", { hour12: false })} </span>
                <span style={{ color: a ? COLOR[a.label] : "#fff" }}>{a?.short ?? m.agent}</span>
                <span className="text-white/80">: {m.text}</span>
              </div>
            );
          })}
          <div ref={end} />
        </div>
      )}
    </div>
  );
}
