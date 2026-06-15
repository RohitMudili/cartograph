"use client";

/**
 * GraphField3D — a calm, depth-real version of the hero graph.
 *
 * Same intent as the 2D GraphField: it shows the visual language of Cartograph
 * (a knowledge graph holding itself in space) and is illustrative, not live
 * telemetry. The 3D adds genuine depth because a real codebase graph is spatial.
 * the engine here (instanced nodes, edge lines, spring-damped parallax) is the
 * seed of the real, event-driven Mission Control graph.
 *
 * Restraint: slow drift, pointer parallax that is spring-damped (never 1:1), no
 * auto-rotate-for-show, amber reserved for important nodes. Perf: instanced
 * meshes, capped DPR, render loop pauses when the hero scrolls out of view.
 */
import { Billboard } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

// Desaturated agent-ramp hues (DESIGN.md) for region tint; amber is reserved.
const AGENT_HUES = [250, 160, 320, 50, 200];
const AMBER = new THREE.Color("#fab03c");
const NODE_COUNT = 90;

interface NodeDatum {
  pos: THREE.Vector3;
  important: boolean;
  baseScale: number;
  color: THREE.Color;
  phase: number;
}

function buildGraph(): { nodes: NodeDatum[]; edges: [number, number][] } {
  // Deterministic PRNG so the layout is stable across renders.
  let seed = 20260616;
  const rand = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  const nodes: NodeDatum[] = [];
  for (let i = 0; i < NODE_COUNT; i++) {
    const important = rand() < 0.09; // amber stays rare
    const hue = AGENT_HUES[Math.floor(rand() * AGENT_HUES.length)];
    const color = important
      ? AMBER.clone()
      : new THREE.Color().setHSL(hue / 360, 0.28, 0.66);
    nodes.push({
      pos: new THREE.Vector3(
        (rand() - 0.5) * 9,
        (rand() - 0.5) * 5.5,
        (rand() - 0.5) * 5.5, // real z-depth
      ),
      important,
      baseScale: important ? 0.12 + rand() * 0.05 : 0.045 + rand() * 0.04,
      color,
      phase: rand() * Math.PI * 2,
    });
  }

  // Connect each node to its 2 nearest neighbours for a graph-like mesh.
  const edges: [number, number][] = [];
  const seen = new Set<string>();
  for (let i = 0; i < nodes.length; i++) {
    const near = nodes
      .map((n, j) => ({ j, d: nodes[i].pos.distanceTo(n.pos) }))
      .filter((o) => o.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, 2);
    for (const { j } of near) {
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      if (!seen.has(key)) {
        seen.add(key);
        edges.push([i, j]);
      }
    }
  }
  return { nodes, edges };
}

function Scene() {
  const group = useRef<THREE.Group>(null);
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const { nodes, edges } = useMemo(() => buildGraph(), []);
  const pointer = useThree((s) => s.pointer);

  // Spring-damped parallax target; the group eases toward it (never snaps).
  const target = useRef({ x: 0, y: 0 });
  const dummy = useMemo(() => new THREE.Object3D(), []);

  // Static instance colours (set once).
  const colorAttr = useMemo(() => {
    const arr = new Float32Array(nodes.length * 3);
    nodes.forEach((n, i) => n.color.toArray(arr, i * 3));
    return arr;
  }, [nodes]);

  // Edge line geometry.
  const lineGeom = useMemo(() => {
    const positions = new Float32Array(edges.length * 2 * 3);
    edges.forEach(([a, b], k) => {
      nodes[a].pos.toArray(positions, k * 6);
      nodes[b].pos.toArray(positions, k * 6 + 3);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, [edges, nodes]);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    // Ease parallax toward pointer (subtle: a few degrees of tilt).
    target.current.x = pointer.y * 0.18;
    target.current.y = pointer.x * 0.26;
    if (group.current) {
      group.current.rotation.x += (target.current.x - group.current.rotation.x) * Math.min(1, delta * 2.4);
      group.current.rotation.y += (target.current.y - group.current.rotation.y) * Math.min(1, delta * 2.4);
    }

    // Gentle per-node bob + important-node pulse, written into the instances.
    const mesh = meshRef.current;
    if (mesh) {
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const bob = Math.sin(t * 0.5 + n.phase) * 0.06;
        dummy.position.set(n.pos.x, n.pos.y + bob, n.pos.z);
        const pulse = n.important ? 1 + Math.sin(t * 1.6 + n.phase) * 0.12 : 1;
        dummy.scale.setScalar(n.baseScale * pulse);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
    }
  });

  return (
    <group ref={group}>
      {/* edges, behind nodes */}
      <lineSegments geometry={lineGeom}>
        <lineBasicMaterial color="#6a7286" transparent opacity={0.22} />
      </lineSegments>

      {/* nodes */}
      <instancedMesh ref={meshRef} args={[undefined, undefined, nodes.length]}>
        <sphereGeometry args={[1, 16, 16]}>
          <instancedBufferAttribute attach="attributes-color" args={[colorAttr, 3]} />
        </sphereGeometry>
        <meshStandardMaterial
          vertexColors
          emissive="#ffffff"
          emissiveIntensity={0.5}
          roughness={0.35}
          metalness={0.1}
        />
      </instancedMesh>

      {/* a tight amber glint on the important nodes (a hint of light, not bloom) */}
      {nodes.map((n, i) =>
        n.important ? (
          <Billboard key={i} position={n.pos}>
            <mesh>
              <circleGeometry args={[n.baseScale * 1.7, 24]} />
              <meshBasicMaterial
                color={AMBER}
                transparent
                opacity={0.07}
                blending={THREE.AdditiveBlending}
                depthWrite={false}
              />
            </mesh>
          </Billboard>
        ) : null,
      )}
    </group>
  );
}

/** Pauses the render loop while the canvas is scrolled out of view. */
function FrameGate({ canvasEl }: { canvasEl: React.RefObject<HTMLDivElement | null> }) {
  const setFrameloop = useThree((s) => s.setFrameloop);

  useEffect(() => {
    const el = canvasEl.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([e]) => setFrameloop(e.isIntersecting ? "always" : "never"),
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [canvasEl, setFrameloop]);

  return null;
}

export function GraphField3D() {
  const wrap = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={wrap}
      className="h-full w-full"
      style={{
        maskImage:
          "radial-gradient(ellipse 85% 75% at 60% 45%, #000 50%, transparent 100%)",
        WebkitMaskImage:
          "radial-gradient(ellipse 85% 75% at 60% 45%, #000 50%, transparent 100%)",
      }}
    >
      <Canvas
        camera={{ position: [0, 0, 9], fov: 50 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      >
        <ambientLight intensity={1.1} />
        <pointLight position={[6, 4, 8]} intensity={6} color="#fab03c" />
        <pointLight position={[-8, -3, 4]} intensity={4} color="#4f7fd0" />
        <Scene />
        <FrameGate canvasEl={wrap} />
      </Canvas>
    </div>
  );
}
