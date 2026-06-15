"use client";

/**
 * GraphField — the landing hero's living centerpiece.
 *
 * A self-contained canvas animation that shows the *visual language* of
 * Cartograph: a knowledge graph assembling itself — nodes blooming into view,
 * edges drawing in, important nodes glowing amber. It is illustrative of the
 * concept (not a claim of live telemetry — no fake numbers, honoring PRODUCT.md's
 * "never simulate real data" rule). The real, event-driven version lives in
 * Mission Control once the agent fleet exists.
 *
 * Motion craft (emil-design-eng): nodes bloom from a visible scale (never 0),
 * strong ease-out settling, hardware-friendly canvas, reduced-motion → a static
 * settled graph. Runs on a single rAF loop, transform/alpha only.
 */

import { useEffect, useRef } from "react";

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number; // target radius (importance)
  born: number; // ms timestamp when it appears
  important: boolean;
  hue: number; // agent-ramp tint
}

interface Edge {
  a: number;
  b: number;
  born: number;
}

// Desaturated agent-ramp hues (DESIGN.md) for region tint; amber is reserved.
const AGENT_HUES = [250, 160, 320, 50, 200, 0];
const AMBER = "250, 176, 60"; // ~oklch(0.84 0.165 91) in rgb-ish, for glow

export function GraphField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const context = el.getContext("2d");
    if (!context) return;
    // Non-null aliases the nested closures can capture without re-narrowing.
    const canvas: HTMLCanvasElement = el;
    const ctx: CanvasRenderingContext2D = context;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let width = 0;
    let height = 0;
    let dpr = 1;
    const nodes: Node[] = [];
    const edges: Edge[] = [];

    // Deterministic pseudo-random so the layout is stable across renders.
    let seed = 1337;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };

    function build() {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      nodes.length = 0;
      edges.length = 0;

      const count = Math.min(64, Math.max(28, Math.floor((width * height) / 14000)));
      const t0 = reduce ? -10000 : 0; // reduced motion: everything already "born"

      for (let i = 0; i < count; i++) {
        const important = rand() < 0.16;
        nodes.push({
          x: width * (0.12 + rand() * 0.76),
          y: height * (0.12 + rand() * 0.76),
          vx: 0,
          vy: 0,
          r: important ? 4.5 + rand() * 3 : 1.6 + rand() * 1.6,
          born: t0 + (reduce ? 0 : rand() * 5200),
          important,
          hue: AGENT_HUES[Math.floor(rand() * AGENT_HUES.length)],
        });
      }
      // Edges: connect each node to a couple of nearby ones (a real-ish graph).
      for (let i = 0; i < nodes.length; i++) {
        const near = nodes
          .map((n, j) => ({ j, d: dist(nodes[i], n) }))
          .filter((o) => o.j !== i)
          .sort((p, q) => p.d - q.d)
          .slice(0, 2 + Math.floor(rand() * 2));
        for (const { j } of near) {
          if (!edges.some((e) => (e.a === i && e.b === j) || (e.a === j && e.b === i))) {
            edges.push({ a: i, b: j, born: Math.max(nodes[i].born, nodes[j].born) + 180 });
          }
        }
      }
    }

    function dist(a: { x: number; y: number }, b: { x: number; y: number }) {
      return Math.hypot(a.x - b.x, a.y - b.y);
    }

    const start = performance.now();

    function frame(now: number) {
      const t = now - start;
      ctx.clearRect(0, 0, width, height);

      // Gentle force settle (subtle drift toward equilibrium, organic feel).
      if (!reduce) {
        for (let i = 0; i < nodes.length; i++) {
          const n = nodes[i];
          n.x += Math.sin((now / 3200) + i) * 0.06;
          n.y += Math.cos((now / 3600) + i * 1.3) * 0.06;
        }
      }

      // Edges first (behind nodes).
      for (const e of edges) {
        const a = nodes[e.a];
        const b = nodes[e.b];
        const draw = reduce ? 1 : clamp((t - e.born) / 600, 0, 1);
        if (draw <= 0) continue;
        const eased = easeOut(draw);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(a.x + (b.x - a.x) * eased, a.y + (b.y - a.y) * eased);
        ctx.strokeStyle = `rgba(120, 130, 150, ${0.1 * eased})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Nodes.
      for (const n of nodes) {
        const age = reduce ? 1 : clamp((t - n.born) / 700, 0, 1);
        if (age <= 0) continue;
        // Bloom from scale 0.9, never 0 (emil-design-eng).
        const eased = easeOut(age);
        const scale = 0.9 + 0.1 * eased;
        const r = n.r * scale;
        const alpha = eased;

        if (n.important) {
          // amber glow halo for important nodes
          const pulse = reduce ? 0.5 : 0.5 + 0.5 * Math.sin(now / 900 + n.x);
          const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 6);
          glow.addColorStop(0, `rgba(${AMBER}, ${0.28 * alpha * (0.6 + 0.4 * pulse)})`);
          glow.addColorStop(1, `rgba(${AMBER}, 0)`);
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r * 6, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = `rgba(${AMBER}, ${alpha})`;
        } else {
          ctx.fillStyle = `hsla(${n.hue}, 35%, 62%, ${0.55 * alpha})`;
        }
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();
      }

      if (!reduce) raf = requestAnimationFrame(frame);
    }

    build();
    if (reduce) {
      // Draw a single settled frame.
      frame(start + 10000);
    } else {
      raf = requestAnimationFrame(frame);
    }

    const onResize = () => {
      cancelAnimationFrame(raf);
      build();
      if (reduce) frame(start + 10000);
      else raf = requestAnimationFrame(frame);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="absolute inset-0 h-full w-full"
      style={{ maskImage: "radial-gradient(ellipse 80% 70% at 60% 45%, #000 55%, transparent 100%)" }}
    />
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}
// Strong ease-out (cubic-bezier(0.23,1,0.32,1) approximation) — emil-design-eng.
function easeOut(t: number) {
  return 1 - Math.pow(1 - t, 3);
}
