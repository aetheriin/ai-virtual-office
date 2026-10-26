"use client";

import { useAnimations, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Component, useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";
import type { AgentId, AgentState } from "@/lib/agents";
import {
  BLINK_MORPHS, MOUTH_MORPHS, VISEMES, mouthAt, pickClip, retargetClips, speechSeconds, type AvatarConfig,
} from "@/lib/avatars";
import { BUBBLE_MS, useOffice } from "@/lib/store";

type MorphMesh = THREE.Mesh & { morphTargetDictionary: Record<string, number>; morphTargetInfluences: number[] };

/** Falls back to the voxel avatar when a .glb is missing or broken, instead of crashing the scene. */
export class AvatarBoundary extends Component<{ fallback: ReactNode; url: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err: unknown) {
    console.warn(`[avatar] gagal memuat ${this.props.url}, kembali ke avatar voxel:`, err);
  }
  componentDidUpdate(prev: { url: string }) {
    if (prev.url !== this.props.url && this.state.failed) this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Scale to `height`, stand on y=0 and centre on x/z. Uses the bind-pose bounding box. */
function normalize(obj: THREE.Object3D, height: number) {
  obj.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(obj, true);
  const size = box.getSize(new THREE.Vector3());
  const scale = size.y > 0 ? height / size.y : 1;
  const center = box.getCenter(new THREE.Vector3());
  return { scale, offset: new THREE.Vector3(-center.x * scale, -box.min.y * scale, -center.z * scale) };
}

function findMorphs(root: THREE.Object3D) {
  const meshes: MorphMesh[] = [];
  root.traverse((o) => {
    const m = o as MorphMesh;
    if (m.isMesh && m.morphTargetDictionary && m.morphTargetInfluences) meshes.push(m);
  });
  const has = (name: string) => meshes.some((m) => name in m.morphTargetDictionary);
  return {
    meshes,
    mouth: MOUTH_MORPHS.find(has) ?? null,
    visemes: has(VISEMES.a),
    blink: BLINK_MORPHS.filter(has),
  };
}

function setMorph(meshes: MorphMesh[], name: string, value: number, k = 0.35) {
  for (const m of meshes) {
    const i = m.morphTargetDictionary[name];
    if (i !== undefined) m.morphTargetInfluences[i] += (value - m.morphTargetInfluences[i]) * k;
  }
}

export function GlbAvatar({ id, config, state, seated }: {
  id: AgentId; config: AvatarConfig; state: AgentState; seated: boolean;
}) {
  const gltf = useGLTF(config.url);
  // useGLTF suspends per URL; with no extra clip files we reuse the (cached) avatar URL
  const extraUrls = config.animations?.length ? config.animations : [config.url];
  const extras = useGLTF(extraUrls) as unknown as { animations: THREE.AnimationClip[] }[];
  const group = useRef<THREE.Group>(null);

  const model = useMemo(() => {
    const scene = cloneSkinned(gltf.scene);
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
        m.frustumCulled = false; // skinned meshes animate outside their bind-pose bounds
      }
    });
    return scene;
  }, [gltf.scene]);

  const fit = useMemo(() => normalize(model, config.height ?? 1.85), [model, config.height]);

  const clips = useMemo(() => {
    const own = gltf.animations ?? [];
    const external = config.animations?.length
      ? retargetClips(extras.flatMap((e) => e.animations ?? []), model, config.rootMotion)
      : [];
    const byName = new Map<string, THREE.AnimationClip>();
    for (const c of [...external, ...own]) byName.set(c.name, c); // embedded clips win on name clashes
    return [...byName.values()];
  }, [gltf.animations, extras, model, config.animations, config.rootMotion]);

  const morphs = useMemo(() => findMorphs(model), [model]);
  const { actions, mixer } = useAnimations(clips, group);

  useEffect(() => {
    console.info(
      `[avatar] ${id}: ${config.url} · ${clips.length} clip (${clips.map((c) => c.name).join(", ") || "-"})` +
      ` · lip-sync: ${morphs.visemes ? "visemes" : morphs.mouth ?? "tidak ada"} · blink: ${morphs.blink.join("/") || "tidak ada"}`,
    );
  }, [id, config.url, clips, morphs]);

  // Cross-fade to the clip that matches the agent's state
  const current = useRef<THREE.AnimationAction | null>(null);
  useLayoutEffect(() => {
    const clip = pickClip(clips, state, { seated, overrides: config.clips });
    const next = clip ? actions[clip.name] : null;
    if (!next || next === current.current) return;
    next.reset().setEffectiveWeight(1).fadeIn(current.current ? 0.35 : 0).play();
    current.current?.fadeOut(0.35);
    current.current = next;
  }, [state, seated, clips, actions, config.clips]);

  useEffect(() => () => { mixer.stopAllAction(); }, [mixer]);

  // Text-driven lip-sync + blinking
  const nextBlink = useRef(2);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const bubble = useOffice.getState().bubbles[id];
    let open = 0;
    let vowel: keyof typeof VISEMES | null = null;
    if (bubble) {
      const spoken = (Date.now() - (bubble.until - BUBBLE_MS)) / 1000;
      if (spoken >= 0 && spoken < speechSeconds(bubble.text)) ({ open, vowel } = mouthAt(bubble.text, spoken));
    }
    if (morphs.visemes) {
      for (const [v, name] of Object.entries(VISEMES)) setMorph(morphs.meshes, name, v === vowel ? open : 0);
      if (!vowel && open > 0) setMorph(morphs.meshes, VISEMES.a, open * 0.5);
    } else if (morphs.mouth) {
      setMorph(morphs.meshes, morphs.mouth, open);
    }
    if (morphs.blink.length) {
      const closing = t > nextBlink.current && t < nextBlink.current + 0.13;
      if (t > nextBlink.current + 0.13) nextBlink.current = t + 2.5 + Math.random() * 3;
      for (const b of morphs.blink) setMorph(morphs.meshes, b, closing ? 1 : 0, 0.6);
    }
  });

  const [ox, oy, oz] = config.offset ?? [0, 0, 0];
  return (
    <group ref={group} rotation={[0, config.rotationY ?? 0, 0]} position={[fit.offset.x + ox, fit.offset.y + oy, fit.offset.z + oz]}>
      <primitive object={model} scale={fit.scale} />
    </group>
  );
}

export function preloadAvatar(config: AvatarConfig) {
  useGLTF.preload(config.url);
  config.animations?.forEach((u) => useGLTF.preload(u));
}
