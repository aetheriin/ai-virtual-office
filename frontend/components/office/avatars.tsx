"use client";

import { Html, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useReducer, useRef } from "react";
import * as THREE from "three";
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js";
import type { AgentDef, AgentState } from "@/lib/agents";
import { useOffice } from "@/lib/store";
import { Box } from "./props";

const SKIN = "#f1c7a0";
const HAIR = ["#3b2416", "#5a3a22", "#1f1a17", "#7a4a2a", "#2b2b2b", "#4a2f1c"];
const LABEL_COLORS = { cyan: "#5fe6ff", green: "#4dff7c", orange: "#ff8a2a", red: "#ff4d5e" } as const;

type Parts = { root: THREE.Group | null; head: THREE.Object3D | null; armL: THREE.Object3D | null; armR: THREE.Object3D | null };

/** Shared per-state procedural animation (replaces Mixamo clips when no .glb is set). */
function useAnimate(parts: React.MutableRefObject<Parts>, state: AgentState, seed: number, baseY = 0) {
  useFrame(({ clock }) => {
    const t = clock.elapsedTime + seed;
    const { root, head, armL, armR } = parts.current;
    if (!root) return;
    let bob = Math.sin(t * 1.6) * 0.015;
    let la = 0, ra = 0, headTilt = 0, headTurn = 0;
    switch (state) {
      case "typing":
        la = -1.2 + Math.sin(t * 18) * 0.12;
        ra = -1.2 + Math.cos(t * 18) * 0.12;
        bob = Math.sin(t * 9) * 0.01;
        break;
      case "thinking":
        headTilt = Math.sin(t * 1.2) * 0.18;
        ra = -2.2;
        bob = Math.sin(t * 2) * 0.03;
        break;
      case "standing":
        la = -0.9;
        ra = Math.sin(t * 2.5) * 0.5 - 0.6;
        headTurn = Math.sin(t * 0.8) * 0.3;
        bob = Math.abs(Math.sin(t * 3)) * 0.05;
        break;
      case "debating":
        ra = -1.6 + Math.sin(t * 6) * 0.9;
        la = Math.sin(t * 3) * 0.3;
        headTilt = Math.sin(t * 6) * 0.08;
        bob = Math.abs(Math.sin(t * 6)) * 0.06;
        break;
    }
    const k = 0.18;
    root.position.y = baseY + bob;
    if (armL) armL.rotation.x += (la - armL.rotation.x) * k;
    if (armR) armR.rotation.x += (ra - armR.rotation.x) * k;
    if (head) {
      head.rotation.z += (headTilt - head.rotation.z) * k;
      head.rotation.y += (headTurn - head.rotation.y) * k;
    }
  });
}

function Arm({ side, color, hand, setRef, length = 0.55 }: { side: 1 | -1; color: string; hand: string; setRef: (o: THREE.Object3D | null) => void; length?: number }) {
  return (
    <group ref={setRef} position={[side * 0.33, 1.32, 0]}>
      <Box position={[0, -length / 2, 0]} size={[0.16, length, 0.18]} color={color} />
      <Box position={[0, -length - 0.06, 0]} size={[0.15, 0.13, 0.15]} color={hand} />
    </group>
  );
}

function Human({ def, state, seated }: { def: AgentDef; state: AgentState; seated: boolean }) {
  const parts = useRef<Parts>({ root: null, head: null, armL: null, armR: null });
  const seed = def.position[0] * 3.1 + def.position[2];
  const hair = HAIR[Math.abs(Math.round(seed)) % HAIR.length];
  useAnimate(parts, state, seed, seated ? -0.25 : 0);
  const suit = def.id === "pm";
  return (
    <group ref={(g) => { parts.current.root = g; }}>
      {/* legs */}
      {seated ? (
        <>
          <Box position={[-0.12, 0.5, -0.18]} size={[0.18, 0.16, 0.5]} color="#1d2638" />
          <Box position={[0.12, 0.5, -0.18]} size={[0.18, 0.16, 0.5]} color="#1d2638" />
          <Box position={[-0.12, 0.25, -0.4]} size={[0.17, 0.45, 0.17]} color="#1d2638" />
          <Box position={[0.12, 0.25, -0.4]} size={[0.17, 0.45, 0.17]} color="#1d2638" />
        </>
      ) : (
        <>
          <Box position={[-0.12, 0.38, 0]} size={[0.19, 0.76, 0.2]} color="#1d2638" />
          <Box position={[0.12, 0.38, 0]} size={[0.19, 0.76, 0.2]} color="#1d2638" />
          <Box position={[-0.12, 0.04, 0.04]} size={[0.2, 0.08, 0.28]} color="#0b0f18" />
          <Box position={[0.12, 0.04, 0.04]} size={[0.2, 0.08, 0.28]} color="#0b0f18" />
        </>
      )}
      {/* torso */}
      <Box position={[0, 1.07, 0]} size={[0.52, 0.62, 0.3]} color={def.color} />
      {suit && <Box position={[0, 1.12, 0.155]} size={[0.07, 0.42, 0.02]} color="#d6312b" />}
      {suit && <Box position={[0, 1.25, 0.152]} size={[0.2, 0.16, 0.01]} color="#f4f4f4" />}
      <Arm side={-1} color={def.color} hand={SKIN} setRef={(o) => { parts.current.armL = o; }} />
      <Arm side={1} color={def.color} hand={SKIN} setRef={(o) => { parts.current.armR = o; }} />
      {suit && <Box position={[0.36, 0.85, 0.2]} size={[0.32, 0.42, 0.03]} color="#f6f6f6" />}
      {/* head */}
      <group ref={(o) => { parts.current.head = o; }} position={[0, 1.42, 0]}>
        <Box position={[0, 0.24, 0]} size={[0.44, 0.44, 0.42]} color={SKIN} />
        <Box position={[0, 0.48, -0.02]} size={[0.48, 0.12, 0.46]} color={hair} />
        <Box position={[0, 0.3, -0.22]} size={[0.48, 0.42, 0.06]} color={hair} />
        <Box position={[-0.1, 0.26, 0.215]} size={[0.06, 0.07, 0.01]} color="#141414" />
        <Box position={[0.1, 0.26, 0.215]} size={[0.06, 0.07, 0.01]} color="#141414" />
        {(def.id === "analyst" || def.id === "qa") && (
          <Box position={[0, 0.3, 0]} size={[0.5, 0.06, 0.48]} color="#2b2b2b" />
        )}
      </group>
    </group>
  );
}

function Bull({ def, state }: { def: AgentDef; state: AgentState }) {
  const parts = useRef<Parts>({ root: null, head: null, armL: null, armR: null });
  useAnimate(parts, state, 1.3);
  const c = def.color;
  return (
    <group ref={(g) => { parts.current.root = g; }} scale={1.25}>
      <Box position={[-0.16, 0.36, 0]} size={[0.24, 0.72, 0.26]} color="#3fcf34" />
      <Box position={[0.16, 0.36, 0]} size={[0.24, 0.72, 0.26]} color="#3fcf34" />
      <Box position={[-0.16, 0.04, 0.02]} size={[0.26, 0.08, 0.3]} color="#1b3a16" />
      <Box position={[0.16, 0.04, 0.02]} size={[0.26, 0.08, 0.3]} color="#1b3a16" />
      <Box position={[0, 1.08, 0]} size={[0.66, 0.72, 0.44]} color={c} />
      <Box position={[0, 1.0, 0.225]} size={[0.4, 0.4, 0.02]} color="#8dff7a" />
      <Box position={[0, 0.75, -0.3]} size={[0.06, 0.06, 0.3]} color={c} rotation={[0.5, 0, 0]} />
      <Arm side={-1} color={c} hand="#2b5a24" setRef={(o) => { parts.current.armL = o; }} length={0.6} />
      <Arm side={1} color={c} hand="#2b5a24" setRef={(o) => { parts.current.armR = o; }} length={0.6} />
      <group ref={(o) => { parts.current.head = o; }} position={[0, 1.46, 0.02]}>
        <Box position={[0, 0.25, 0]} size={[0.56, 0.5, 0.5]} color={c} />
        <Box position={[0, 0.14, 0.3]} size={[0.38, 0.24, 0.14]} color="#ff9fb0" />
        <Box position={[-0.08, 0.15, 0.375]} size={[0.06, 0.06, 0.01]} color="#5a2030" />
        <Box position={[0.08, 0.15, 0.375]} size={[0.06, 0.06, 0.01]} color="#5a2030" />
        <Box position={[-0.14, 0.36, 0.255]} size={[0.1, 0.05, 0.01]} color="#102a0c" />
        <Box position={[0.14, 0.36, 0.255]} size={[0.1, 0.05, 0.01]} color="#102a0c" />
        {/* horns */}
        {[-1, 1].map((s) => (
          <group key={s} position={[s * 0.34, 0.48, 0]}>
            <Box position={[s * 0.06, 0, 0]} size={[0.16, 0.1, 0.12]} color="#f1e3b0" />
            <Box position={[s * 0.13, 0.12, 0]} size={[0.08, 0.2, 0.08]} color="#f1e3b0" />
          </group>
        ))}
      </group>
    </group>
  );
}

function Bear({ def, state }: { def: AgentDef; state: AgentState }) {
  const parts = useRef<Parts>({ root: null, head: null, armL: null, armR: null });
  useAnimate(parts, state, 2.7);
  const c = def.color;
  return (
    <group ref={(g) => { parts.current.root = g; }} scale={1.3}>
      <Box position={[-0.17, 0.34, 0]} size={[0.28, 0.68, 0.3]} color="#7d1b2b" />
      <Box position={[0.17, 0.34, 0]} size={[0.28, 0.68, 0.3]} color="#7d1b2b" />
      <Box position={[0, 1.06, 0]} size={[0.74, 0.8, 0.5]} color={c} />
      <Box position={[0, 1.0, 0.255]} size={[0.44, 0.5, 0.02]} color="#c4505f" />
      <Arm side={-1} color={c} hand="#5a1220" setRef={(o) => { parts.current.armL = o; }} length={0.62} />
      <Arm side={1} color={c} hand="#5a1220" setRef={(o) => { parts.current.armR = o; }} length={0.62} />
      <group ref={(o) => { parts.current.head = o; }} position={[0, 1.48, 0]}>
        <Box position={[0, 0.25, 0]} size={[0.58, 0.52, 0.5]} color={c} />
        <Box position={[0, 0.14, 0.29]} size={[0.3, 0.2, 0.1]} color="#d9828d" />
        <Box position={[0, 0.2, 0.345]} size={[0.1, 0.07, 0.01]} color="#200508" />
        <Box position={[-0.14, 0.34, 0.255]} size={[0.08, 0.06, 0.01]} color="#160306" />
        <Box position={[0.14, 0.34, 0.255]} size={[0.08, 0.06, 0.01]} color="#160306" />
        <Box position={[-0.15, 0.42, 0.256]} size={[0.14, 0.035, 0.01]} color="#160306" rotation={[0, 0, -0.35]} />
        <Box position={[0.15, 0.42, 0.256]} size={[0.14, 0.035, 0.01]} color="#160306" rotation={[0, 0, 0.35]} />
        <Box position={[-0.25, 0.55, 0]} size={[0.16, 0.16, 0.12]} color={c} />
        <Box position={[0.25, 0.55, 0]} size={[0.16, 0.16, 0.12]} color={c} />
      </group>
    </group>
  );
}

function RiskOrb({ def, state }: { def: AgentDef; state: AgentState }) {
  const ref = useRef<THREE.Group>(null);
  const body = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const active = state !== "idle";
    if (ref.current) ref.current.position.y = 0.9 + Math.sin(t * (active ? 3 : 1.2)) * (active ? 0.08 : 0.04);
    if (body.current) body.current.emissiveIntensity = active ? 0.35 + Math.sin(t * 6) * 0.2 : 0.12;
  });
  return (
    <group>
      {/* judge chair */}
      <Box position={[0, 0.45, -0.1]} size={[0.8, 0.1, 0.7]} color="#1d2433" />
      <Box position={[0, 1.0, -0.45]} size={[0.8, 1.1, 0.1]} color="#1d2433" />
      <group ref={ref}>
        <mesh castShadow>
          <sphereGeometry args={[0.55, 20, 16]} />
          <meshStandardMaterial ref={body} color={def.color} emissive={def.color} emissiveIntensity={0.12} roughness={0.6} flatShading />
        </mesh>
        <Box position={[-0.17, 0.08, 0.52]} size={[0.14, 0.03, 0.02]} color="#4a1d00" />
        <Box position={[0.17, 0.08, 0.52]} size={[0.14, 0.03, 0.02]} color="#4a1d00" />
        <Box position={[0, -0.12, 0.535]} size={[0.12, 0.025, 0.02]} color="#4a1d00" />
        <Box position={[0, -0.42, 0.42]} size={[0.24, 0.1, 0.04]} color="#f4f4f4" />
        <Box position={[0, -0.52, 0.45]} size={[0.07, 0.2, 0.02]} color="#2357d6" />
      </group>
    </group>
  );
}

function GlbAvatar({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const cloned = useMemo(() => cloneSkinned(scene), [scene]);
  return <primitive object={cloned} />;
}

const SEATED = new Set(["analyst", "qa", "fe", "be", "db"]);

export function AgentAvatar({ def }: { def: AgentDef }) {
  const state = useOffice((s) => s.states[def.id]);
  const bubble = useOffice((s) => s.bubbles[def.id]);
  const ring = useRef<THREE.Mesh>(null);
  const [, rerender] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (!bubble) return;
    const id = setTimeout(rerender, Math.max(0, bubble.until - Date.now()) + 50);
    return () => clearTimeout(id);
  }, [bubble]);
  const active = state !== "idle";
  const showBubble = bubble && bubble.until > Date.now();
  const labelColor = LABEL_COLORS[def.label];

  useFrame(({ clock }) => {
    if (!ring.current) return;
    const m = ring.current.material as THREE.MeshBasicMaterial;
    m.opacity = active ? 0.45 + Math.sin(clock.elapsedTime * 5) * 0.25 : 0;
    ring.current.scale.setScalar(active ? 1 + Math.sin(clock.elapsedTime * 5) * 0.06 : 1);
  });

  const voxel =
    def.kind === "bull" ? <Bull def={def} state={state} /> :
    def.kind === "bear" ? <Bear def={def} state={state} /> :
    def.kind === "orb" ? <RiskOrb def={def} state={state} /> :
    <Human def={def} state={state} seated={SEATED.has(def.id)} />;

  const headY = def.kind === "human" ? 2.3 : def.kind === "orb" ? 1.9 : 2.75;

  return (
    <group position={def.position}>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[0.55, 0.7, 32]} />
        <meshBasicMaterial color={labelColor} transparent opacity={0} toneMapped={false} />
      </mesh>
      <group rotation={[0, def.rotation, 0]}>
        {def.glb ? <Suspense fallback={voxel}><GlbAvatar url={def.glb} /></Suspense> : voxel}
      </group>

      <Html position={[0, headY, 0]} center zIndexRange={[16, 1]} pointerEvents="none">
        <div className="flex flex-col items-center gap-1">
          {showBubble && (
            <div className="bubble font-term w-[230px] text-[15px] leading-[1.05]">
              {bubble.text.length > 170 ? bubble.text.slice(0, 167) + "..." : bubble.text}
            </div>
          )}
          {active && !showBubble && <div className="bubble font-pixel text-[10px] animate-pulse">{state === "typing" ? "⌨ ..." : "..."}</div>}
        </div>
      </Html>
      <Html position={[0, def.kind === "human" ? -0.05 : -0.1, 0.9]} center zIndexRange={[15, 1]} pointerEvents="none">
        <div
          className="font-pixel whitespace-nowrap rounded-[3px] border-2 bg-night-950/85 px-2 py-1 text-[10px]"
          style={{ color: labelColor, borderColor: labelColor, boxShadow: `0 0 10px ${labelColor}66` }}
        >
          {def.short}
        </div>
      </Html>
    </group>
  );
}
