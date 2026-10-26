import type { AgentId, AgentState, Dept } from "./agents";

export interface AgentMessage {
  id: number;
  session_id: string;
  agent: AgentId;
  kind: string;
  text: string;
  data?: unknown;
  at: number;
}

export interface Task {
  id: string;
  title: string;
  assignee: AgentId;
  depends_on?: string[];
  done_when?: string;
  status: "todo" | "doing" | "done";
}

export interface Candle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Proposal {
  side: "LONG" | "SHORT";
  score: number;
  evidence: string[];
  entry: number;
  stop_loss: number;
  tp1: number;
  tp2: number;
  trigger: string;
  thesis: string;
  risks: string[];
  rr_tp1: number;
  rr_tp2: number;
}

export interface NewsHeadline {
  title: string;
  source: string;
  url: string;
  published: string;
  score: number;
  method: "alphavantage" | "llm" | "lexicon";
  high_impact: boolean;
}

export interface NewsSentiment {
  symbol: string;
  score: number;
  label: "bullish" | "bearish" | "neutral" | "no_data";
  count: number;
  sources: string[];
  event_risk: boolean;
  strong: boolean;
  headlines: NewsHeadline[];
}

export interface TradingPlan {
  session_id: string;
  symbol: string;
  asset_class: string;
  interval: string;
  status: "BUY" | "SELL" | "WAIT";
  bias: "LONG" | "SHORT";
  price: number;
  as_of: string;
  entry: number;
  stop_loss: number;
  tp1: number;
  tp2: number;
  rr_tp1: number;
  rr_tp2: number;
  trigger: string;
  position: { quantity: number; unit: string; risk_amount: number; max_loss: number; notional: number; note: string };
  capital: number;
  risk_pct: number;
  account_currency: string;
  scores: { bull: number; bear: number };
  reasons: string[];
  summary: string;
  data_source: string;
  demo: boolean;
  bull: Proposal;
  bear: Proposal;
  news: NewsSentiment | null;
}

export interface ItResult {
  session_id: string;
  prompt: string;
  plan: { summary: string; assumptions?: string[]; tasks: Omit<Task, "status">[] };
  analysis: { user_stories?: string[]; acceptance_criteria?: string[]; edge_cases?: string[]; open_questions?: string[] };
  code: Partial<Record<"db" | "be" | "fe", string>>;
  review: { verdict: string; findings?: { severity: string; agent: string; issue: string }[]; tests?: string[] };
}

export type AgentStates = Record<AgentId, AgentState>;
export type Busy = Record<Dept, boolean>;

export interface Project {
  id: number;
  name: string;
  description: string;
  repo: string | null;
  base_branch: string | null;
  runs: number;
  last_run_at: string | null;
  created_at: string;
}

export interface PullRequestInfo {
  status: "none" | "pending" | "opened" | "draft" | "skipped" | "failed";
  url: string | null;
  number: number | null;
  branch: string | null;
  error: string | null;
}

export interface RunSummary {
  id: string;
  project_id: number;
  prompt: string;
  status: "running" | "done" | "failed";
  summary: string;
  review_verdict: string | null;
  created_at: string;
  finished_at: string | null;
  pr: PullRequestInfo;
}

export interface RunDetail extends RunSummary {
  assumptions: string[];
  analysis: ItResult["analysis"];
  review: ItResult["review"];
  error: string | null;
  tasks: Task[];
  code: ItResult["code"];
  findings: { severity: string; agent: string; issue: string }[];
}
