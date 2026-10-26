"use client";

import { io, type Socket } from "socket.io-client";
import { create } from "zustand";
import { AGENTS, BACKEND_URL, type AgentId, type AgentState, type Dept } from "./agents";
import type { AgentMessage, AgentStates, Busy, Candle, ItResult, Task, TradingPlan } from "./types";

const BUBBLE_MS = 9000;

interface OfficeState {
  connected: boolean;
  llmEnabled: boolean;
  busy: Busy;
  error: string | null;
  states: AgentStates;
  messages: AgentMessage[];
  /** Latest line each agent said, shown in the 3D chat bubble until it expires */
  bubbles: Partial<Record<AgentId, { text: string; until: number }>>;
  tasks: Task[];
  itResult: ItResult | null;
  plan: TradingPlan | null;
  market: { symbol: string; source: string; interval: string; candles: Candle[] } | null;
  focus: Dept | null;
  setFocus: (d: Dept | null) => void;
  analyze: (args: { symbol: string; interval: string; capital?: number; risk_pct?: number; account_currency: string }) => Promise<void>;
  requestIt: (prompt: string) => Promise<void>;
  clearError: () => void;
}

const idleStates = () => Object.fromEntries(AGENTS.map((a) => [a.id, "idle"])) as AgentStates;
let socket: Socket | null = null;
let msgSeq = 0;

export const useOffice = create<OfficeState>((set, get) => ({
  connected: false,
  llmEnabled: false,
  busy: { it: false, trade: false },
  error: null,
  states: idleStates(),
  messages: [],
  bubbles: {},
  tasks: [],
  itResult: null,
  plan: null,
  market: null,
  focus: null,
  setFocus: (focus) => set({ focus }),
  clearError: () => set({ error: null }),

  analyze: async (args) => {
    const res = await emitAck("trade:analyze", args);
    if (!res.ok) set({ error: res.error ?? "Gagal memulai analisa" });
    else set({ plan: null, focus: "trade" });
  },

  requestIt: async (prompt) => {
    const res = await emitAck("it:request", { prompt });
    if (!res.ok) set({ error: res.error ?? "Gagal mengirim permintaan" });
    else set({ tasks: [], itResult: null, focus: "it" });
  },
}));

function emitAck(event: string, data: unknown): Promise<{ ok: boolean; error?: string }> {
  return new Promise((resolve) => {
    if (!socket?.connected) return resolve({ ok: false, error: "Backend tidak terhubung (cek uvicorn di port 8000)" });
    socket.timeout(10_000).emit(event, data, (err: Error | null, res: { ok: boolean; error?: string }) =>
      resolve(err ? { ok: false, error: "Backend tidak merespons" } : res),
    );
  });
}

/** Connect once (idempotent). Called from the page on mount. */
export function connectOffice() {
  if (socket) return;
  socket = io(BACKEND_URL, { transports: ["websocket", "polling"], reconnectionDelay: 1500 });
  const set = useOffice.setState;
  const get = useOffice.getState;

  socket.on("connect", () => set({ connected: true }));
  socket.on("disconnect", () => set({ connected: false }));
  socket.on("hello", (d: { llm_enabled: boolean; busy: Dept[] }) =>
    set({ llmEnabled: d.llm_enabled, busy: { it: d.busy.includes("it"), trade: d.busy.includes("trade") } }),
  );

  socket.on("job:start", (d: { dept: Dept }) => set({ busy: { ...get().busy, [d.dept]: true } }));
  socket.on("job:end", (d: { dept: Dept }) => set({ busy: { ...get().busy, [d.dept]: false } }));
  socket.on("job:error", (d: { error: string }) => set({ error: d.error, states: idleStates() }));

  socket.on("agent:status", (d: { agent: AgentId; state: AgentState }) =>
    set({ states: { ...get().states, [d.agent]: d.state } }),
  );

  socket.on("agent:message", (d: Omit<AgentMessage, "id" | "at">) => {
    const msg: AgentMessage = { ...d, id: ++msgSeq, at: Date.now() };
    set({
      messages: [...get().messages.slice(-199), msg],
      bubbles: { ...get().bubbles, [d.agent]: { text: d.text, until: Date.now() + BUBBLE_MS } },
    });
  });

  socket.on("it:tasks", (d: { tasks: Task[] }) => set({ tasks: d.tasks }));
  socket.on("it:task_status", (d: { assignee: AgentId; status: Task["status"] }) =>
    set({ tasks: get().tasks.map((t) => (t.assignee === d.assignee ? { ...t, status: d.status } : t)) }),
  );
  socket.on("it:result", (d: ItResult) => set({ itResult: d }));
  socket.on("trade:market", (d: OfficeState["market"]) => set({ market: d }));
  socket.on("trade:plan", (d: TradingPlan) => set({ plan: d }));
}
