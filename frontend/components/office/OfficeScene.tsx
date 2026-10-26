"use client";

import { Html, OrbitControls, OrthographicCamera } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { AGENTS } from "@/lib/agents";
import { useOffice } from "@/lib/store";
import { AgentAvatar } from "./avatars";
import { Bars, Box, Chair, ChartLine, Desk, Floor, PALETTE, Plant, Screen, ServerRack, Wall, WallSign } from "./props";

/*
 * World layout (top view, +x right, +z towards the camera):
 *
 *   z=-11 ┌───────── Ruang Debat (core) ─────────┐
 *         │                                       │
 *   z=-6  ├──── Departemen IT ───┬── Investasi ───┤
 *         │  racks  desks  PM    │ bull table bear│
 *   z=+6  └──────────────────────┴────────────────┘
 *        x=-11                  x=0             x=11
 */

const FOCUS_TARGETS = {
  it: { target: new THREE.Vector3(-3.2, 0.5, -0.5), zoom: 60 },
  trade: { target: new THREE.Vector3(7.6, 0.5, -1), zoom: 64 },
  all: { target: new THREE.Vector3(3.2, 0.5, -3.2), zoom: 38 },
};

function CameraRig({ controls }: { controls: React.RefObject<OrbitControlsImpl | null> }) {
  const focus = useOffice((s) => s.focus);
  const { camera, size } = useThree();
  const dest = FOCUS_TARGETS[focus ?? "all"];
  const settle = useRef(0);
  const lastFocus = useRef<typeof focus | "init">("init");
  // Fit the whole office on narrow (phone) screens and lift it above the bottom sheet
  const fit = Math.min(1, size.width / 1100);
  const mobile = size.width < 640;
  const goal = useMemo(() => (mobile ? dest.target.clone().add(new THREE.Vector3(0, -3.2, 0)) : dest.target), [dest, mobile]);

  useFrame(() => {
    if (lastFocus.current !== focus) {
      lastFocus.current = focus;
      settle.current = 90; // animate for ~1.5s, then hand control back to the user
    }
    if (settle.current <= 0 || !controls.current) return;
    settle.current--;
    const c = controls.current;
    const offset = camera.position.clone().sub(c.target);
    c.target.lerp(goal, 0.08);
    camera.position.copy(c.target).add(offset);
    const cam = camera as THREE.OrthographicCamera;
    cam.zoom += (Math.max(16, dest.zoom * fit * (mobile ? 1.15 : 1)) - cam.zoom) * 0.08;
    cam.updateProjectionMatrix();
    c.update();
  });
  return null;
}

function DebateCore() {
  const crystal = useRef<THREE.Group>(null);
  const particles = useRef<THREE.Points>(null);
  const busy = useOffice((s) => s.busy.trade || s.busy.it);
  const count = 160;
  const { positions, colors, speeds } = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const speeds = new Float32Array(count);
    const palette = [new THREE.Color(PALETTE.green), new THREE.Color(PALETTE.orange), new THREE.Color("#ff4fd8"), new THREE.Color(PALETTE.cyan)];
    for (let i = 0; i < count; i++) {
      const r = 0.4 + Math.random() * 2.2;
      const a = Math.random() * Math.PI * 2;
      positions.set([Math.cos(a) * r, Math.random() * 5, Math.sin(a) * r], i * 3);
      palette[i % palette.length].toArray(colors, i * 3);
      speeds[i] = 0.3 + Math.random() * 0.9;
    }
    return { positions, colors, speeds };
  }, []);

  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime;
    if (crystal.current) {
      crystal.current.rotation.y = t * (busy ? 1.4 : 0.4);
      crystal.current.position.y = 1.8 + Math.sin(t * 1.5) * 0.12;
    }
    const geo = particles.current?.geometry;
    if (!geo) return;
    const pos = geo.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < count; i++) {
      let y = pos.getY(i) + dt * speeds[i] * (busy ? 2.2 : 0.7);
      if (y > 5) y = 0;
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
  });

  return (
    <group position={[0, 0, -8.6]}>
      <Box position={[0, 0.25, 0]} size={[1.6, 0.5, 1.6]} color="#162238" emissive={PALETTE.green} emissiveIntensity={0.15} />
      <group ref={crystal}>
        <mesh>
          <octahedronGeometry args={[0.75, 0]} />
          <meshStandardMaterial color="#9bff3a" emissive="#4dff7c" emissiveIntensity={busy ? 2.2 : 1.1} flatShading toneMapped={false} />
        </mesh>
        <mesh scale={0.55} rotation={[0.4, 0.6, 0]}>
          <octahedronGeometry args={[0.75, 0]} />
          <meshStandardMaterial color="#ffb347" emissive="#ff8a2a" emissiveIntensity={1.6} flatShading toneMapped={false} />
        </mesh>
      </group>
      <points ref={particles}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        </bufferGeometry>
        <pointsMaterial size={0.12} vertexColors transparent opacity={0.9} toneMapped={false} sizeAttenuation />
      </points>
      <pointLight position={[0, 2, 0]} color={PALETTE.green} intensity={busy ? 30 : 14} distance={9} />
    </group>
  );
}

function StatusScreen() {
  const connected = useOffice((s) => s.connected);
  const llm = useOffice((s) => s.llmEnabled);
  const busy = useOffice((s) => s.busy);
  return (
    <Screen position={[3.4, 2.1, -10.85]} w={3.6} h={2.0} glow={PALETTE.cyan}>
      <Html transform distanceFactor={4.2} pointerEvents="none" zIndexRange={[5, 0]}>
        <div className="font-pixel w-[330px] text-[11px] leading-6 text-neon-cyan" style={{ textShadow: "0 0 6px #5fe6ff" }}>
          <div className="mb-2 text-[20px]">RUANG DEBAT</div>
          <div>STATUS KONEKSI API: <span className={connected ? "text-neon-green" : "text-neon-red"}>{connected ? "ONLINE" : "OFFLINE"}</span></div>
          <div>MODE AI: <span className={llm ? "text-neon-green" : "text-neon-orange"}>{llm ? "LLM AKTIF" : "RULE ENGINE"}</span></div>
          <div>IT: {busy.it ? "BEKERJA" : "SIAGA"} · ARENA: {busy.trade ? "DEBAT" : "SIAGA"}</div>
        </div>
      </Html>
    </Screen>
  );
}

function KanbanBoard() {
  const tasks = useOffice((s) => s.tasks);
  const cols = [
    { key: "todo", label: "TODO", color: "#ff8a2a" },
    { key: "doing", label: "DOING", color: "#5fe6ff" },
    { key: "done", label: "DONE", color: "#4dff7c" },
  ] as const;
  return (
    <Screen position={[-10.84, 2.0, -1.4]} rotation={Math.PI / 2} w={3.0} h={1.9} glow={PALETTE.green}>
      <Html transform distanceFactor={4.2} pointerEvents="none" zIndexRange={[5, 0]}>
        <div className="font-term grid w-[300px] grid-cols-3 gap-1 text-[13px] leading-4 text-white">
          {cols.map((c) => (
            <div key={c.key}>
              <div className="font-pixel mb-1 text-[8px]" style={{ color: c.color }}>{c.label}</div>
              {tasks.filter((t) => t.status === c.key).slice(0, 4).map((t) => (
                <div key={t.id} className="mb-1 rounded-sm px-1 py-0.5" style={{ background: `${c.color}22`, borderLeft: `2px solid ${c.color}` }}>
                  {t.id} {t.title.slice(0, 26)}
                </div>
              ))}
              {tasks.length === 0 && c.key === "todo" && <div className="text-white/40">menunggu brief...</div>}
            </div>
          ))}
        </div>
      </Html>
    </Screen>
  );
}

function TradingTable() {
  const plan = useOffice((s) => s.plan);
  const busy = useOffice((s) => s.busy.trade);
  const color = plan?.status === "BUY" ? PALETTE.green : plan?.status === "SELL" ? PALETTE.red : PALETTE.orange;
  return (
    <group position={[5.6, 0, 1.0]}>
      <Box position={[0, 0.78, 0]} size={[3.4, 0.1, 1.7]} color="#13233a" emissive={PALETTE.green} emissiveIntensity={0.1} />
      <Box position={[-1.5, 0.38, 0]} size={[0.1, 0.76, 1.4]} color={PALETTE.desk} />
      <Box position={[1.5, 0.38, 0]} size={[0.1, 0.76, 1.4]} color={PALETTE.desk} />
      <Html transform position={[0, 0.84, 0]} rotation={[-Math.PI / 2, 0, 0]} distanceFactor={4.4} pointerEvents="none" zIndexRange={[5, 0]}>
        <div className="font-pixel w-[300px] text-center text-[11px] leading-5" style={{ color, textShadow: `0 0 8px ${color}` }}>
          <div className="text-[14px]">TRADING PLAN</div>
          {plan ? (
            <>
              <div className="text-[18px]">{plan.symbol} · {plan.status}</div>
              <div>E {plan.entry} · SL {plan.stop_loss}</div>
              <div>TP1 {plan.tp1} · TP2 {plan.tp2}</div>
            </>
          ) : (
            <div className="text-neon-green/70">{busy ? "DEBAT BERLANGSUNG..." : "MENUNGGU ANALISA"}</div>
          )}
        </div>
      </Html>
    </group>
  );
}

function MarketScreen() {
  const market = useOffice((s) => s.market);
  const closes = useMemo(() => market?.candles.map((c) => c.c), [market]);
  const up = closes && closes.length > 1 ? closes[closes.length - 1] >= closes[0] : true;
  return (
    <Screen position={[3.6, 1.5, -5.85]} w={2.8} h={1.7} glow={PALETTE.green}>
      <ChartLine w={2.5} h={1.3} trend={1} color={up ? PALETTE.green : PALETTE.red} points={closes} seed={7} />
      {market && (
        <Html transform position={[-0.6, 0.7, 0]} distanceFactor={4} pointerEvents="none" zIndexRange={[5, 0]}>
          <div className="font-pixel text-[10px] text-neon-green">{market.symbol} · {market.interval} · {market.source}</div>
        </Html>
      )}
    </Screen>
  );
}

function Office() {
  const itBusy = useOffice((s) => s.busy.it);
  return (
    <>
      {/* floors */}
      <Floor x={-5.5} z={0} w={11} d={12} />
      <Floor x={5.5} z={0} w={11} d={12} />
      <Floor x={0} z={-8.5} w={9} d={5} />

      {/* outer walls (cut-away diorama: only the far walls are drawn) */}
      <Wall from={[-11, -6]} to={[-11, 6]} />
      <Wall from={[-11, -6]} to={[-1.8, -6]} />
      <Wall from={[1.8, -6]} to={[11, -6]} />
      <Wall from={[-4.5, -11]} to={[4.5, -11]} trim={PALETTE.green} />
      <Wall from={[-4.5, -11]} to={[-4.5, -6]} trim={PALETTE.green} />
      <Wall from={[4.5, -11]} to={[4.5, -6]} trim={PALETTE.green} />
      {/* divider between IT and Investasi with a doorway */}
      <Wall from={[0, -4.4]} to={[0, 1.2]} height={2.6} />
      <Wall from={[0, 2.8]} to={[0, 6]} height={2.6} />
      <Box position={[0, 1.1, 2.0]} size={[0.24, 2.2, 1.5]} color="#0e1830" emissive={PALETTE.cyan} emissiveIntensity={0.08} />

      {/* ---------------- Departemen IT ---------------- */}
      <WallSign position={[-6.5, 2.85, -5.86]} text="Departemen IT" color={PALETTE.orange} size={24} />
      <ServerRack position={[-10.4, 0, -4.8]} rotation={Math.PI / 2} busy={itBusy} />
      <ServerRack position={[-10.4, 0, -3.7]} rotation={Math.PI / 2} busy={itBusy} />
      <ServerRack position={[-9.0, 0, -5.4]} busy={itBusy} />
      <ServerRack position={[-10.4, 0, 3.6]} rotation={Math.PI / 2} busy={itBusy} />
      <Screen position={[-8.4, 1.75, -5.85]} w={2.4} h={1.3} glow={PALETTE.green}>
        <Bars w={2.1} h={1.05} color={PALETTE.green} seed={11} />
      </Screen>
      <Screen position={[-4.4, 1.75, -5.85]} w={2.4} h={1.3} glow={PALETTE.orange}>
        <ChartLine w={2.1} h={0.95} trend={0.6} color={PALETTE.orange} seed={5} />
      </Screen>
      <KanbanBoard />

      {/* PM standing by the board */}
      <Desk position={[-8.4, 0, 1.4]} rotation={Math.PI / 2} monitors={1} />
      {/* analyst + QA desks along back wall */}
      <Desk position={[-6.2, 0, -4.2]} monitors={2} />
      <Chair position={[-6.2, 0, -3.3]} />
      <Desk position={[-3.6, 0, -4.2]} monitors={3} screenColor={PALETTE.cyan} />
      <Chair position={[-3.6, 0, -3.3]} />
      {/* FE & BE desks side by side (facing each other) */}
      <Desk position={[-3.5, 0, 0]} rotation={Math.PI / 2} monitors={2} />
      <Desk position={[-3.5, 0, 1.5]} rotation={Math.PI / 2} monitors={2} screenColor={PALETTE.cyan} />
      <Chair position={[-4.6, 0, 0.6]} rotation={-Math.PI / 2} />
      <Chair position={[-2.4, 0, -0.6]} rotation={Math.PI / 2} />
      {/* DB engineer */}
      <Desk position={[-5.6, 0, 4.2]} rotation={Math.PI} monitors={2} />
      <Chair position={[-5.6, 0, 3.3]} rotation={Math.PI} />
      <Plant position={[-1.0, 0, 5.3]} />

      {/* ---------------- Departemen Investasi ---------------- */}
      <WallSign position={[8.0, 2.85, -5.86]} text="Departemen Investasi" color={PALETTE.orange} size={18} />
      <WallSign position={[3.6, 2.85, -5.86]} text="BULL AGENT" color={PALETTE.green} size={16} />
      <MarketScreen />
      <Screen position={[9.5, 1.55, -5.85]} w={2.4} h={1.6} glow={PALETTE.red}>
        <ChartLine w={2.1} h={1.3} trend={-1} color={PALETTE.red} seed={19} />
      </Screen>
      <Screen position={[6.6, 1.55, -5.85]} w={2.0} h={1.5} glow={PALETTE.orange}>
        <ChartLine w={1.8} h={1.2} trend={0.2} color={PALETTE.orange} seed={23} />
      </Screen>
      <TradingTable />
      <Plant position={[10.2, 0, -5.2]} />
      <WallSign position={[6.2, 0.03, 4.6]} flat text="Departemen Investasi" color={PALETTE.green} size={22} />

      {/* ---------------- Ruang Debat (core) ---------------- */}
      <Box position={[-1.8, 1.6, -6]} size={[0.3, 3.2, 0.3]} color={PALETTE.wall} emissive={PALETTE.green} emissiveIntensity={0.25} />
      <Box position={[1.8, 1.6, -6]} size={[0.3, 3.2, 0.3]} color={PALETTE.wall} emissive={PALETTE.green} emissiveIntensity={0.25} />
      <DebateCore />
      <StatusScreen />

      {AGENTS.map((a) => <AgentAvatar key={a.id} def={a} />)}
    </>
  );
}

export default function OfficeScene() {
  const controls = useRef<OrbitControlsImpl>(null);
  return (
    <Canvas shadows dpr={[1, 2]} gl={{ antialias: true }} className="!absolute inset-0">
      <color attach="background" args={["#070c18"]} />
      <fog attach="fog" args={["#070c18", 60, 120]} />
      <OrthographicCamera makeDefault position={[22, 22, 26]} zoom={38} near={-100} far={300} />
      <OrbitControls
        ref={controls}
        makeDefault
        target={[3.2, 0.5, -3.2]}
        enableDamping
        minZoom={14}
        maxZoom={140}
        minPolarAngle={0.5}
        maxPolarAngle={1.15}
        minAzimuthAngle={0.15}
        maxAzimuthAngle={1.35}
      />
      <CameraRig controls={controls} />
      <ambientLight intensity={0.35} color="#8aa4ff" />
      <hemisphereLight args={["#6f8cff", "#0a0f1c", 0.35]} />
      <directionalLight position={[10, 18, 8]} intensity={0.9} castShadow shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-16} shadow-camera-right={16} shadow-camera-top={16} shadow-camera-bottom={-16} />
      <pointLight position={[-6, 3, 0]} color={PALETTE.green} intensity={18} distance={12} />
      <pointLight position={[6, 3, 0]} color={PALETTE.orange} intensity={14} distance={12} />
      <pointLight position={[8.5, 2.5, -4]} color={PALETTE.red} intensity={10} distance={7} />
      <Office />
    </Canvas>
  );
}
