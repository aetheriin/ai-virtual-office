"use client";

import { Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";

export const PALETTE = {
  floor: "#0d1628",
  floorTile: "#111d33",
  wall: "#121c30",
  wallDark: "#0c1424",
  trim: "#ff7a1a",
  green: "#4dff7c",
  red: "#ff4d5e",
  orange: "#ff8a2a",
  cyan: "#5fe6ff",
  desk: "#1b2940",
  deskTop: "#22324f",
  metal: "#2a3346",
};

type Vec3 = [number, number, number];

export function Box({ position, size, color, emissive, emissiveIntensity = 1, rotation }: {
  position: Vec3; size: Vec3; color: string; emissive?: string; emissiveIntensity?: number; rotation?: Vec3;
}) {
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} emissive={emissive ?? "#000"} emissiveIntensity={emissive ? emissiveIntensity : 0} roughness={0.85} metalness={0.1} toneMapped={!emissive} />
    </mesh>
  );
}

/** Wall with a glowing trim line along its top edge. */
export function Wall({ from, to, height = 3.2, thickness = 0.22, trim = PALETTE.trim }: {
  from: [number, number]; to: [number, number]; height?: number; thickness?: number; trim?: string;
}) {
  const [x1, z1] = from;
  const [x2, z2] = to;
  const len = Math.hypot(x2 - x1, z2 - z1);
  const angle = -Math.atan2(z2 - z1, x2 - x1);
  const cx = (x1 + x2) / 2;
  const cz = (z1 + z2) / 2;
  return (
    <group position={[cx, 0, cz]} rotation={[0, angle, 0]}>
      <Box position={[0, height / 2, 0]} size={[len, height, thickness]} color={PALETTE.wall} />
      <Box position={[0, height + 0.03, 0]} size={[len, 0.06, thickness + 0.02]} color={trim} emissive={trim} emissiveIntensity={1.6} />
      <Box position={[0, 0.05, 0]} size={[len, 0.1, thickness + 0.04]} color={PALETTE.wallDark} />
    </group>
  );
}

export function Floor({ x, z, w, d }: { x: number; z: number; w: number; d: number }) {
  return (
    <group position={[x, 0, z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial color={PALETTE.floor} roughness={0.95} />
      </mesh>
      <gridHelper args={[Math.max(w, d), Math.max(w, d), PALETTE.floorTile, PALETTE.floorTile]} position={[0, 0.005, 0]} scale={[w / Math.max(w, d), 1, d / Math.max(w, d)]} />
      {/* orange edge trim on the open (front) sides, like the reference art */}
      <Box position={[0, 0.03, d / 2]} size={[w, 0.06, 0.08]} color={PALETTE.trim} emissive={PALETTE.trim} emissiveIntensity={1.4} />
      <Box position={[w / 2, 0.03, 0]} size={[0.08, 0.06, d]} color={PALETTE.trim} emissive={PALETTE.trim} emissiveIntensity={1.4} />
    </group>
  );
}

/** Wall-mounted screen: dark panel + glowing bezel + arbitrary content. */
export function Screen({ position, rotation = 0, w, h, glow = PALETTE.green, children }: {
  position: Vec3; rotation?: number; w: number; h: number; glow?: string; children?: ReactNode;
}) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Box position={[0, 0, 0]} size={[w + 0.12, h + 0.12, 0.06]} color="#05080f" emissive={glow} emissiveIntensity={0.35} />
      <mesh position={[0, 0, 0.035]}>
        <planeGeometry args={[w, h]} />
        <meshBasicMaterial color="#050a14" />
      </mesh>
      <group position={[0, 0, 0.05]}>{children}</group>
    </group>
  );
}

/** Procedural line chart drawn inside a screen; trend > 0 goes up, < 0 goes down. */
export function ChartLine({ w, h, trend, color, seed = 1, points: given }: {
  w: number; h: number; trend: number; color: string; seed?: number; points?: number[];
}) {
  const pts = useMemo(() => {
    let values = given;
    if (!values || values.length < 2) {
      let s = seed;
      const rand = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
      values = Array.from({ length: 28 }, (_, i) => i * trend + (rand() - 0.5) * 4);
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values.map((v, i) => new THREE.Vector3(-w / 2 + (i / (values!.length - 1)) * w, -h / 2 + ((v - min) / span) * h, 0));
  }, [w, h, trend, seed, given]);
  return <Line points={pts} color={color} lineWidth={2.2} toneMapped={false} />;
}

export function Bars({ w, h, color, seed = 3, count = 14 }: { w: number; h: number; color: string; seed?: number; count?: number }) {
  const bars = useMemo(() => {
    let s = seed;
    const rand = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    return Array.from({ length: count }, (_, i) => ({ x: -w / 2 + (i + 0.5) * (w / count), hh: (0.25 + rand() * 0.75) * h * (0.5 + i / count / 2) }));
  }, [w, h, seed, count]);
  return (
    <>
      {bars.map((b, i) => (
        <mesh key={i} position={[b.x, -h / 2 + b.hh / 2, 0]}>
          <planeGeometry args={[(w / count) * 0.6, b.hh]} />
          <meshBasicMaterial color={i % 4 === 3 ? PALETTE.red : color} toneMapped={false} />
        </mesh>
      ))}
    </>
  );
}

export function Desk({ position, rotation = 0, monitors = 2, screenColor = PALETTE.green }: {
  position: Vec3; rotation?: number; monitors?: number; screenColor?: string;
}) {
  const offsets = Array.from({ length: monitors }, (_, i) => (i - (monitors - 1) / 2) * 0.62);
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Box position={[0, 0.74, 0]} size={[1.6, 0.08, 0.8]} color={PALETTE.deskTop} />
      <Box position={[-0.72, 0.36, 0]} size={[0.08, 0.72, 0.72]} color={PALETTE.desk} />
      <Box position={[0.72, 0.36, 0]} size={[0.08, 0.72, 0.72]} color={PALETTE.desk} />
      {offsets.map((x, i) => (
        <group key={i} position={[x, 0.78, -0.22]}>
          <Box position={[0, 0.06, 0]} size={[0.08, 0.12, 0.08]} color={PALETTE.metal} />
          <Box position={[0, 0.38, 0]} size={[0.56, 0.4, 0.05]} color="#0a0f1a" />
          <mesh position={[0, 0.38, 0.03]}>
            <planeGeometry args={[0.5, 0.34]} />
            <meshBasicMaterial color={screenColor} transparent opacity={0.55} toneMapped={false} />
          </mesh>
        </group>
      ))}
      <Box position={[0, 0.8, 0.15]} size={[0.6, 0.03, 0.2]} color="#0c1220" />
    </group>
  );
}

export function Chair({ position, rotation = 0 }: { position: Vec3; rotation?: number }) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Box position={[0, 0.45, 0]} size={[0.55, 0.08, 0.55]} color="#1d2433" />
      <Box position={[0, 0.85, 0.25]} size={[0.55, 0.7, 0.08]} color="#1d2433" />
      <Box position={[0, 0.22, 0]} size={[0.08, 0.44, 0.08]} color={PALETTE.metal} />
      <Box position={[0, 0.03, 0]} size={[0.5, 0.05, 0.5]} color={PALETTE.metal} />
    </group>
  );
}

/** Server rack with blinking LEDs (the busy department makes them blink faster). */
export function ServerRack({ position, rotation = 0, busy = false }: { position: Vec3; rotation?: number; busy?: boolean }) {
  const leds = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime * (busy ? 9 : 2.5);
    leds.current?.children.forEach((c, i) => {
      const m = (c as THREE.Mesh).material as THREE.MeshBasicMaterial;
      m.opacity = 0.25 + 0.75 * (Math.sin(t + i * 1.7) > 0.2 ? 1 : 0);
    });
  });
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <Box position={[0, 1.1, 0]} size={[0.9, 2.2, 0.8]} color="#0f1626" />
      <group ref={leds} position={[0, 0, 0.41]}>
        {Array.from({ length: 18 }, (_, i) => (
          <mesh key={i} position={[-0.3 + (i % 3) * 0.3, 0.35 + Math.floor(i / 3) * 0.3, 0]}>
            <planeGeometry args={[0.16, 0.04]} />
            <meshBasicMaterial color={i % 5 === 0 ? PALETTE.orange : PALETTE.green} transparent toneMapped={false} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

export function Plant({ position }: { position: Vec3 }) {
  return (
    <group position={position}>
      <Box position={[0, 0.2, 0]} size={[0.35, 0.4, 0.35]} color="#6b3d24" />
      <Box position={[0, 0.65, 0]} size={[0.16, 0.6, 0.16]} color="#3f8f3a" />
      <Box position={[0.14, 0.75, 0]} size={[0.12, 0.3, 0.12]} color="#3f8f3a" />
      <Box position={[-0.13, 0.62, 0]} size={[0.12, 0.22, 0.12]} color="#3f8f3a" />
    </group>
  );
}

/** Neon sign painted on a wall (DOM rendered in 3D so the pixel font is used). */
export function WallSign({ position, rotation = 0, text, color, size = 26, flat = false }: {
  position: Vec3; rotation?: number; text: string; color: string; size?: number; flat?: boolean;
}) {
  return (
    <Html transform position={position} rotation={flat ? [-Math.PI / 2, 0, rotation] : [0, rotation, 0]} distanceFactor={6} pointerEvents="none" zIndexRange={[5, 0]}>
      <div className="font-pixel whitespace-nowrap select-none" style={{ color, fontSize: size, textShadow: `0 0 8px ${color}, 0 0 22px ${color}` }}>
        {text}
      </div>
    </Html>
  );
}
