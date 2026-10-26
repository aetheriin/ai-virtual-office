"use client";

import * as THREE from "three";
import { create } from "zustand";
import type { AgentId, AgentState } from "./agents";

/**
 * Avatar manifest: /public/avatars/manifest.json (read at runtime, so dropping in new .glb files
 * needs no rebuild). Agents without an entry keep their procedural voxel avatar.
 *
 * {
 *   "defaults": { "animations": ["/avatars/mixamo-pack.glb"] },
 *   "agents": {
 *     "pm":   { "url": "/avatars/pm.glb", "height": 1.8 },
 *     "bull": { "url": "/avatars/bull.glb", "height": 2.4, "clips": { "debating": "Arguing" } }
 *   }
 * }
 */
export interface AvatarConfig {
  url: string;
  /** Target height in world units (≈ metres). The model is scaled to fit. */
  height?: number;
  /** Extra clip files (e.g. Mixamo exports) merged with the clips embedded in `url` */
  animations?: string[];
  /** Explicit clip per state, overrides name matching */
  clips?: Partial<Record<AgentState | "sitting" | "talking", string>>;
  rotationY?: number;
  offset?: [number, number, number];
  /** Keep Hips position tracks from external clips (off by default: Mixamo exports them in cm) */
  rootMotion?: boolean;
}

export interface AvatarManifest {
  defaults?: Partial<Omit<AvatarConfig, "url">>;
  agents?: Partial<Record<AgentId, AvatarConfig>>;
}

interface AvatarStore {
  manifest: AvatarManifest | null;
  loaded: boolean;
}

export const useAvatars = create<AvatarStore>(() => ({ manifest: null, loaded: false }));

let loading: Promise<void> | null = null;

/** Drop entries whose .glb is missing so a typo in the manifest only costs a warning, not an error. */
async function withoutMissingFiles(m: AvatarManifest): Promise<AvatarManifest> {
  const urls = new Set<string>([...(m.defaults?.animations ?? [])]);
  for (const a of Object.values(m.agents ?? {})) {
    if (a?.url) urls.add(a.url);
    a?.animations?.forEach((u) => urls.add(u));
  }
  const missing = new Set<string>();
  await Promise.all([...urls].map(async (u) => {
    const ok = await fetch(u, { method: "HEAD" }).then((r) => r.ok).catch(() => false);
    if (!ok) missing.add(u);
  }));
  if (!missing.size) return m;
  console.warn(`[avatar] file tidak ditemukan, dilewati: ${[...missing].join(", ")}`);
  const agents = Object.fromEntries(Object.entries(m.agents ?? {}).filter(([, a]) => a?.url && !missing.has(a.url)).map(
    ([id, a]) => [id, { ...a!, animations: a!.animations?.filter((u) => !missing.has(u)) }],
  ));
  return { defaults: { ...m.defaults, animations: m.defaults?.animations?.filter((u) => !missing.has(u)) }, agents };
}

export function loadAvatarManifest(url = "/avatars/manifest.json"): Promise<void> {
  loading ??= fetch(url, { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then(async (m: AvatarManifest | null) => {
      const manifest = m && typeof m === "object" && m.agents ? await withoutMissingFiles(m) : null;
      useAvatars.setState({ manifest, loaded: true });
    })
    .catch(() => useAvatars.setState({ manifest: null, loaded: true }));
  return loading;
}

export function avatarFor(manifest: AvatarManifest | null, id: AgentId): AvatarConfig | null {
  const entry = manifest?.agents?.[id];
  if (!entry?.url) return null;
  const d = manifest?.defaults ?? {};
  return {
    ...d,
    ...entry,
    animations: [...(d.animations ?? []), ...(entry.animations ?? [])],
    clips: { ...d.clips, ...entry.clips },
  };
}

// ---------------------------------------------------------------- clips
/** Name fragments tried in order for each state (case-insensitive substring match). */
const CANDIDATES: Record<string, string[]> = {
  idle: ["idle", "breath", "stand"],
  sitting: ["sitting idle", "sit", "seated"],
  typing: ["typing", "type", "keyboard", "computer"],
  thinking: ["thinking", "think", "ponder", "look"],
  standing: ["talking", "talk", "explain", "present", "wave", "idle"],
  debating: ["debat", "argu", "talking", "talk", "gestur", "angry", "idle"],
  talking: ["talking", "talk", "explain"],
};

export function pickClip(
  clips: THREE.AnimationClip[],
  state: AgentState,
  opts: { seated?: boolean; overrides?: AvatarConfig["clips"] } = {},
): THREE.AnimationClip | null {
  if (!clips.length) return null;
  const key = state === "idle" && opts.seated ? "sitting" : state;
  const forced = opts.overrides?.[key as keyof NonNullable<AvatarConfig["clips"]>];
  if (forced) {
    const hit = clips.find((c) => c.name.toLowerCase() === forced.toLowerCase());
    if (hit) return hit;
  }
  const order = [...(CANDIDATES[key] ?? []), ...(key === "sitting" ? CANDIDATES.idle : [])];
  for (const frag of order) {
    const hit = clips.find((c) => c.name.toLowerCase().includes(frag));
    if (hit) return hit;
  }
  return clips.find((c) => /idle/i.test(c.name)) ?? clips[0];
}

const MIXAMO_PREFIX = /^mixamorig\d*[:_]?/i;

/**
 * Make clips from another file (typically Mixamo) play on this skeleton:
 * - strip the "mixamorig" bone prefix (Ready Player Me / Avaturn bones have none),
 * - drop position tracks unless rootMotion (Mixamo exports them in centimetres),
 * - drop tracks whose bone doesn't exist on the target (avoids binding warnings).
 */
export function retargetClips(clips: THREE.AnimationClip[], target: THREE.Object3D, rootMotion = false): THREE.AnimationClip[] {
  const names = new Set<string>();
  target.traverse((o) => names.add(o.name));
  const targetHasPrefix = [...names].some((n) => MIXAMO_PREFIX.test(n));

  return clips.map((clip) => {
    const tracks = clip.tracks.flatMap((t) => {
      const dot = t.name.lastIndexOf(".");
      let node = t.name.slice(0, dot);
      const prop = t.name.slice(dot + 1);
      if (!names.has(node)) {
        const bare = node.replace(MIXAMO_PREFIX, "");
        node = targetHasPrefix ? [...names].find((n) => n.replace(MIXAMO_PREFIX, "") === bare) ?? bare : bare;
      }
      if (!names.has(node)) return [];
      if (prop === "position" && !rootMotion) return [];
      const copy = t.clone();
      copy.name = `${node}.${prop}`;
      return [copy];
    });
    return new THREE.AnimationClip(clip.name, clip.duration, tracks);
  });
}

// ---------------------------------------------------------------- lip sync
/** Ready Player Me / ARKit / Oculus viseme names we know how to drive. */
export const MOUTH_MORPHS = ["mouthOpen", "jawOpen", "viseme_aa", "MouthOpen", "Mouth_Open"];
export const VISEMES = { a: "viseme_aa", e: "viseme_E", i: "viseme_I", o: "viseme_O", u: "viseme_U" } as const;
export const BLINK_MORPHS = ["eyeBlinkLeft", "eyeBlinkRight", "eyesClosed", "Blink"];

/** Text-driven mouth shape (no audio/TTS here, so Rhubarb has nothing to analyse). */
export function mouthAt(text: string, t: number, charsPerSecond = 14): { open: number; vowel: keyof typeof VISEMES | null } {
  const i = Math.floor(t * charsPerSecond);
  if (i < 0 || i >= text.length) return { open: 0, vowel: null };
  const ch = text[i].toLowerCase();
  if ("ao".includes(ch)) return { open: 1, vowel: ch as "a" | "o" };
  if ("eiu".includes(ch)) return { open: 0.6, vowel: ch as "e" | "i" | "u" };
  if (/[a-z0-9]/.test(ch)) return { open: 0.25, vowel: null };
  return { open: 0, vowel: null };
}

/** How long an agent "speaks" a bubble: proportional to the text, capped. */
export function speechSeconds(text: string, charsPerSecond = 14) {
  return Math.min(text.length / charsPerSecond, 8);
}
