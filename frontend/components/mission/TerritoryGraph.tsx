"use client";

/**
 * Territory graph — the Mission Control centerpiece. A 3D field (React Three
 * Fiber, the same engine family as the landing hero) where each node is a symbol
 * the fleet has touched. As explorers read/cite a symbol it BLOOMS in; when the
 * critic verifies it, it locks to amber. So the graph literally fills in as you
 * watch the agents map the codebase.
 *
 * Data source is the reduced run state (touched / verified fqname sets) rather
 * than a separate graph-slice API — it shows exactly what the agents have
 * explored, and needs no extra backend. Lazy-loaded by MissionControl so Three.js
 * stays off the initial bundle; reduced-motion → a static settled frame.
 */

import { Canvas, useFrame } from "@react-three/fiber";
import { useReducedMotion } from "motion/react";
import { useMemo, useRef } from "react";
import * as THREE from "three";

const AMBER = new THREE.Color("#fab03c");
const COOL = new THREE.Color().setHSL(210 / 360, 0.3, 0.62);

interface Placed {
  fqname: string;
  pos: THREE.Vector3;
  verified: boolean;
}

/** Deterministic placement: hash the fqname to a stable position in the field. */
function place(fqname: string): THREE.Vector3 {
  let h = 2166136261;
  for (let i = 0; i < fqname.length; i++) {
    h ^= fqname.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const a = (h & 0xffff) / 0xffff;
  const b = ((h >>> 16) & 0xffff) / 0xffff;
  const c = ((h >>> 8) & 0xff) / 0xff;
  return new THREE.Vector3((a - 0.5) * 11, (b - 0.5) * 6.5, (c - 0.5) * 5);
}

function Field({
  touched,
  verified,
  reduce,
}: {
  touched: string[];
  verified: Set<string>;
  reduce: boolean;
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const placed = useMemo<Placed[]>(
    () => touched.map((fq) => ({ fqname: fq, pos: place(fq), verified: verified.has(fq) })),
    [touched, verified],
  );

  // Edges: connect each node to its 2 nearest, so it reads as a graph.
  const lineGeom = useMemo(() => {
    const segs: number[] = [];
    for (let i = 0; i < placed.length; i++) {
      const near = placed
        .map((q, j) => ({ j, d: placed[i].pos.distanceTo(q.pos) }))
        .filter((o) => o.j !== i)
        .sort((x, y) => x.d - y.d)
        .slice(0, 2);
      for (const { j } of near) {
        segs.push(placed[i].pos.x, placed[i].pos.y, placed[i].pos.z);
        segs.push(placed[j].pos.x, placed[j].pos.y, placed[j].pos.z);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(segs), 3));
    return g;
  }, [placed]);

  const colorAttr = useMemo(() => {
    const arr = new Float32Array(Math.max(placed.length, 1) * 3);
    placed.forEach((n, i) => (n.verified ? AMBER : COOL).toArray(arr, i * 3));
    return arr;
  }, [placed]);

  const born = useRef<Map<string, number>>(new Map());

  useFrame((stateThree) => {
    const t = stateThree.clock.elapsedTime;
    const mesh = meshRef.current;
    if (!mesh) return;
    for (let i = 0; i < placed.length; i++) {
      const n = placed[i];
      if (!born.current.has(n.fqname)) born.current.set(n.fqname, t);
      const age = reduce ? 1 : Math.min(1, (t - (born.current.get(n.fqname) ?? t)) / 0.6);
      const eased = 1 - Math.pow(1 - age, 3);
      const base = n.verified ? 0.16 : 0.09;
      const pulse = !reduce && n.verified ? 1 + Math.sin(t * 1.6 + i) * 0.12 : 1;
      dummy.position.set(n.pos.x, n.pos.y, n.pos.z);
      dummy.scale.setScalar(base * (0.4 + 0.6 * eased) * pulse);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  if (placed.length === 0) return null;

  return (
    <group>
      <lineSegments geometry={lineGeom}>
        <lineBasicMaterial color="#6a7286" transparent opacity={0.18} />
      </lineSegments>
      <instancedMesh ref={meshRef} args={[undefined, undefined, placed.length]}>
        <sphereGeometry args={[1, 16, 16]}>
          <instancedBufferAttribute attach="attributes-color" args={[colorAttr, 3]} />
        </sphereGeometry>
        <meshStandardMaterial
          vertexColors
          emissive="#ffffff"
          emissiveIntensity={0.45}
          roughness={0.35}
        />
      </instancedMesh>
    </group>
  );
}

export function TerritoryGraph({
  touched,
  verified,
}: {
  touched: string[];
  verified: Set<string>;
}) {
  const reduce = useReducedMotion() ?? false;
  return (
    <div className="relative h-full w-full">
      {touched.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center">
          <p className="font-mono text-sm text-faint">
            The map fills in as agents explore the repo…
          </p>
        </div>
      )}
      <Canvas
        camera={{ position: [0, 0, 9], fov: 50 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      >
        <ambientLight intensity={1.1} />
        <pointLight position={[6, 4, 8]} intensity={6} color="#fab03c" />
        <pointLight position={[-8, -3, 4]} intensity={4} color="#4f7fd0" />
        <Field touched={touched} verified={verified} reduce={reduce} />
      </Canvas>
    </div>
  );
}
