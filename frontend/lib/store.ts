"use client";

import { io, type Socket } from "socket.io-client";
import { create } from "zustand";
import { AGENTS, BACKEND_URL, type AgentId, type AgentState, type Dept } from "./agents";
import type {
  AgentMessage, AgentStates, Busy, Candle, ItResult, JournalStats, NewsSentiment, PaperTrade, Project, PullRequestInfo,
  RunDetail, RunSummary, ScreenerResult, Task, TradingPlan,
} from "./types";

export const BUBBLE_MS = 9000;

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
  news: NewsSentiment | null;
  focus: Dept | null;
  projectDb: string | null;
  projects: Project[];
  projectId: number | null;
  runs: RunSummary[];
  /** Sprint loaded from history (read-only view), null = live sprint */
  viewingRun: string | null;
  /** Pull request of the live sprint (or of the sprint opened from history) */
  pr: PullRequestInfo | null;
  github: { configured: boolean; login?: string; error?: string } | null;
  watchlist: string[];
  saveWatchlist: (symbols: string[]) => Promise<boolean>;
  screener: { result: ScreenerResult | null; progress: { stage: string; done: number; total: number } | null; universe: string[] };
  runScreener: (args: { interval: string; capital?: number; risk_pct?: number }) => Promise<void>;
  saveUniverse: (symbols: string[]) => Promise<boolean>;
  journal: { stats: JournalStats | null; trades: PaperTrade[]; loading: boolean };
  loadJournal: (refresh?: boolean) => Promise<void>;
  deleteTrade: (id: number) => Promise<void>;
  loadProjects: () => Promise<void>;
  selectProject: (id: number) => Promise<void>;
  createProject: (p: { name: string; description: string; repo?: string; base_branch?: string }) => Promise<boolean>;
  updateProject: (id: number, patch: { repo?: string; base_branch?: string; description?: string }) => Promise<boolean>;
  openRun: (id: string) => Promise<void>;
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
  busy: { it: false, trade: false, screener: false },
  error: null,
  states: idleStates(),
  messages: [],
  bubbles: {},
  tasks: [],
  itResult: null,
  plan: null,
  market: null,
  news: null,
  focus: null,
  projectDb: null,
  projects: [],
  projectId: null,
  runs: [],
  viewingRun: null,
  pr: null,
  github: null,
  watchlist: [],
  screener: { result: null, progress: null, universe: [] },
  journal: { stats: null, trades: [], loading: false },

  saveWatchlist: async (symbols) => {
    const res = (await send("PUT", "/api/watchlist", { symbols })) as { symbols: string[] } | null;
    if (res) set({ watchlist: res.symbols });
    return !!res;
  },

  runScreener: async (args) => {
    const res = await emitAck("screener:run", args);
    if (!res.ok) set({ error: res.error ?? "Gagal menjalankan screener" });
    else set({ screener: { ...get().screener, progress: { stage: "download", done: 0, total: 0 } }, focus: "trade" });
  },

  saveUniverse: async (symbols) => {
    const res = (await send("PUT", "/api/screener/universe", { symbols })) as { symbols: string[] } | null;
    if (res) set({ screener: { ...get().screener, universe: res.symbols } });
    return !!res;
  },

  loadJournal: async (refresh = false) => {
    set({ journal: { ...get().journal, loading: true } });
    const res = refresh
      ? ((await send("POST", "/api/journal/refresh", {})) as { stats: JournalStats; trades: PaperTrade[] } | null)
      : await api<{ stats: JournalStats; trades: PaperTrade[] }>("/api/journal");
    set({ journal: res ? { stats: res.stats, trades: res.trades, loading: false } : { ...get().journal, loading: false } });
  },

  deleteTrade: async (id) => {
    const res = await fetch(`${BACKEND_URL}/api/journal/${id}`, { method: "DELETE" }).catch(() => null);
    if (res?.ok) await get().loadJournal();
  },
  setFocus: (focus) => set({ focus }),

  loadProjects: async () => {
    const list = await api<Project[]>("/api/projects");
    if (!list) return;
    const current = get().projectId;
    const keep = list.find((p) => p.id === current) ?? list[0];
    set({ projects: list });
    if (keep && keep.id !== current) await get().selectProject(keep.id);
  },

  selectProject: async (id) => {
    set({ projectId: id, runs: [] });
    const runs = await api<RunSummary[]>(`/api/projects/${id}/runs`);
    if (runs && get().projectId === id) set({ runs });
  },

  createProject: async (body) => {
    const res = await send("POST", "/api/projects", body);
    if (!res) return false;
    const p = res as Project;
    set({ projects: [p, ...get().projects] });
    await get().selectProject(p.id);
    return true;
  },

  updateProject: async (id, patch) => {
    const res = await send("PATCH", `/api/projects/${id}`, patch);
    if (!res) return false;
    const p = res as Project;
    set({ projects: get().projects.map((x) => (x.id === id ? { ...x, ...p } : x)) });
    return true;
  },

  openRun: async (id) => {
    const run = await api<RunDetail>(`/api/it/runs/${id}`);
    if (!run) return;
    set({
      viewingRun: id,
      pr: run.pr,
      tasks: run.tasks,
      itResult: run.status === "running" ? null : {
        session_id: run.id, prompt: run.prompt,
        plan: { summary: run.summary, assumptions: run.assumptions, tasks: run.tasks },
        analysis: run.analysis, code: run.code, review: run.review,
      },
    });
  },
  clearError: () => set({ error: null }),

  analyze: async (args) => {
    const res = await emitAck("trade:analyze", args);
    if (!res.ok) set({ error: res.error ?? "Gagal memulai analisa" });
    else set({ plan: null, news: null, focus: "trade" });
  },

  requestIt: async (prompt) => {
    const res = await emitAck("it:request", { prompt, project_id: get().projectId ?? undefined });
    if (!res.ok) set({ error: res.error ?? "Gagal mengirim permintaan" });
    else set({ tasks: [], itResult: null, viewingRun: null, pr: null, focus: "it" });
  },
}));

async function api<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND_URL}${path}`);
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as T;
  } catch {
    useOffice.setState({ error: `Gagal memuat ${path}` });
    return null;
  }
}

/** JSON POST/PATCH; shows the backend's `detail` message on failure. */
async function send(method: string, path: string, body: unknown): Promise<unknown | null> {
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = (data as { detail?: unknown }).detail;
      useOffice.setState({ error: typeof d === "string" ? d : Array.isArray(d) ? "Input tidak valid" : `Gagal (${res.status})` });
      return null;
    }
    return data;
  } catch {
    useOffice.setState({ error: "Backend tidak terhubung" });
    return null;
  }
}

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
  socket.on("hello", (d: { llm_enabled: boolean; busy: (Dept | "screener")[]; project_db?: string }) => {
    set({ llmEnabled: d.llm_enabled, projectDb: d.project_db ?? null, busy: { it: d.busy.includes("it"), trade: d.busy.includes("trade"), screener: d.busy.includes("screener") } });
    void get().loadProjects();
    void api<OfficeState["github"]>("/api/github/status").then((g) => set({ github: g }));
    void api<{ symbols: string[] }>("/api/watchlist").then((w) => w && set({ watchlist: w.symbols }));
    void api<{ symbols: string[] }>("/api/screener/universe").then((u) => u && set({ screener: { ...get().screener, universe: u.symbols } }));
    void api<ScreenerResult | null>("/api/screener/last").then((r) => r && set({ screener: { ...get().screener, result: r } }));
    void get().loadJournal();
  });

  socket.on("job:start", (d: { dept: Dept | "screener" }) => set({ busy: { ...get().busy, [d.dept]: true } }));
  socket.on("job:end", (d: { dept: Dept | "screener" }) => {
    set({ busy: { ...get().busy, [d.dept]: false } });
    if (d.dept === "it") void get().loadProjects().then(() => { const id = get().projectId; if (id) void get().selectProject(id); });
  });
  socket.on("job:error", (d: { error: string; dept?: string }) => {
    set({ error: d.error, states: idleStates() });
    if (d.dept === "screener") set({ screener: { ...get().screener, progress: null } });
  });

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

  socket.on("it:tasks", (d: { tasks: Task[] }) => set({ tasks: d.tasks, viewingRun: null }));
  socket.on("it:task_status", (d: { assignee: AgentId; status: Task["status"] }) =>
    set({ tasks: get().tasks.map((t) => (t.assignee === d.assignee ? { ...t, status: d.status } : t)) }),
  );
  socket.on("it:result", (d: ItResult) => set({ itResult: d }));
  socket.on("it:pr", (d: Partial<PullRequestInfo>) =>
    set({ pr: { status: "none", url: null, number: null, branch: null, error: null, ...d } as PullRequestInfo }));
  socket.on("trade:market", (d: OfficeState["market"]) => set({ market: d }));
  socket.on("trade:news", (d: NewsSentiment) => set({ news: d }));
  socket.on("trade:plan", (d: TradingPlan) => {
    set({ plan: d });
    if (d.paper_trade_id) void get().loadJournal();
  });
  socket.on("screener:progress", (d: { stage: string; done: number; total: number }) =>
    set({ screener: { ...get().screener, progress: d } }));
  socket.on("screener:result", (d: ScreenerResult) => {
    set({ screener: { ...get().screener, result: d, progress: null } });
    void get().loadJournal();
  });
  socket.on("journal:update", () => void get().loadJournal());
}
