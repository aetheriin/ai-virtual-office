export type AgentId = "pm" | "analyst" | "fe" | "be" | "db" | "qa" | "bull" | "bear" | "risk";
export type AgentState = "idle" | "thinking" | "typing" | "standing" | "debating";
export type Dept = "it" | "trade";

export interface AgentDef {
  id: AgentId;
  name: string;
  short: string;
  dept: Dept;
  kind: "human" | "bull" | "bear" | "orb";
  /** World position [x, y, z] and facing (radians around Y) */
  position: [number, number, number];
  rotation: number;
  color: string;
  label: "cyan" | "green" | "orange" | "red";
  /** Optional Ready Player Me / Mixamo .glb in /public/avatars — falls back to the voxel avatar */
  glb?: string;
}

// Left room: Departemen IT (x < 0). Right room: Departemen Investasi (x > 0).
export const AGENTS: AgentDef[] = [
  { id: "pm", name: "Project Manager", short: "PM", dept: "it", kind: "human", position: [-8.6, 0, -1.2], rotation: Math.PI / 2.4, color: "#22324f", label: "cyan" },
  { id: "analyst", name: "Analis Kebutuhan", short: "BA", dept: "it", kind: "human", position: [-6.2, 0, -3.4], rotation: 0, color: "#2f7d4f", label: "cyan" },
  { id: "qa", name: "QA & Reviewer", short: "QA", dept: "it", kind: "human", position: [-3.6, 0, -3.4], rotation: 0, color: "#2b3a55", label: "cyan" },
  { id: "be", name: "Backend Developer", short: "BE", dept: "it", kind: "human", position: [-2.4, 0, -0.6], rotation: -Math.PI / 2, color: "#e8e8e8", label: "cyan" },
  { id: "fe", name: "Frontend Developer", short: "FE", dept: "it", kind: "human", position: [-4.6, 0, 0.6], rotation: Math.PI / 2, color: "#3a6e8f", label: "cyan" },
  { id: "db", name: "Database Engineer", short: "DB", dept: "it", kind: "human", position: [-5.6, 0, 3.2], rotation: Math.PI, color: "#e37a2c", label: "cyan" },
  { id: "bull", name: "Bull Agent", short: "BULL AGENT", dept: "trade", kind: "bull", position: [3.2, 0, 0.9], rotation: Math.PI / 2.2, color: "#5cff4a", label: "green" },
  { id: "risk", name: "Risk Agent", short: "RISK AGENT", dept: "trade", kind: "orb", position: [5.6, 0, -1.3], rotation: 0, color: "#ff8a2a", label: "orange" },
  { id: "bear", name: "Bear Agent", short: "BEAR AGENT", dept: "trade", kind: "bear", position: [8.1, 0, 1.0], rotation: -Math.PI / 2.2, color: "#9b2335", label: "red" },
];

export const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a])) as Record<AgentId, AgentDef>;

export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
