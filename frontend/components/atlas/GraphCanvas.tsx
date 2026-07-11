"use client";

/**
 * Atlas graph canvas — a 2D force-directed rendering of the repo's knowledge
 * graph (nodes + structural edges from `GET /graph`), colored by community.
 *
 * Deliberately a hand-rolled canvas (same family as the landing's 2D
 * GraphField) rather than a graph library: the API caps the slice at a few
 * hundred degree-ranked nodes, well inside what immediate-mode canvas handles
 * at 60fps, and it keeps the bundle small. Layout is Fruchterman–Reingold with
 * a seeded RNG, community-clustered initialization, and progressive ticks over
 * rAF — the map visibly settles into place on load.
 *
 * Interactions: drag = pan · wheel = zoom (about the cursor) · click = select ·
 * hover = tooltip. Selecting (or an external `focusId`) flies the camera to the
 * node. Pure view: selection state lives in the parent.
 */

import { CornersOut, Minus, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef } from "react";

import type { GraphEdge, GraphNode } from "@/lib/api";

interface SimNode {
  n: GraphNode;
  x: number;
  y: number;
  dx: number;
  dy: number;
  r: number;
}

interface Camera {
  x: number; // world coords at screen centre
  y: number;
  scale: number;
}

/** Deterministic RNG so the layout is identical on every visit. */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TICKS = 260;

/** World-space square the layout targets — scales with the graph so a 9-node
 *  repo fills the frame as confidently as a 400-node one. */
function areaFor(count: number): number {
  return Math.min(1200, Math.max(320, Math.sqrt(count) * 90));
}

/* Edge kinds get line styles, not just alpha — imports solid, calls dashed,
   inheritance dotted — so the map reads in grayscale too. */
const EDGE_DASH: Record<string, number[]> = {
  calls: [5, 4],
  inherits: [1.5, 3.5],
  implements: [1.5, 3.5],
};

export function GraphCanvas({
  nodes,
  edges,
  communityColor,
  selectedId,
  focusId,
  dimCommunity,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  communityColor: Map<string, string>;
  selectedId: number | null;
  /** When set (e.g. from search), the camera flies to this node. */
  focusId: number | null;
  /** When set, nodes outside this community dim to background. */
  dimCommunity: string | null;
  onSelect: (id: number | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simRef = useRef<SimNode[]>([]);
  const byIdRef = useRef<Map<number, SimNode>>(new Map());
  const tickRef = useRef(0);
  const camRef = useRef<Camera>({ x: 0, y: 0, scale: 1 });
  const camAnimRef = useRef<{ from: Camera; to: Camera; t0: number } | null>(null);
  const hoverRef = useRef<SimNode | null>(null);
  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const userMovedRef = useRef(false);
  const fitRequestRef = useRef(false);
  const areaRef = useRef(1200);
  const rafRef = useRef(0);

  // Props the draw loop reads without re-initializing the sim.
  const viewRef = useRef({ selectedId, dimCommunity, communityColor });
  useEffect(() => {
    viewRef.current = { selectedId, dimCommunity, communityColor };
  });

  // ── Layout initialization (re-runs only when the data changes) ────────────
  useEffect(() => {
    const rand = mulberry32(nodes.length * 2654435761 + edges.length);
    const area = areaFor(nodes.length);
    areaRef.current = area;
    // Seed each community at a spot on a ring so clusters start separated.
    const communities = [...new Set(nodes.map((n) => n.community ?? "·"))];
    const centre = new Map<string, [number, number]>();
    communities.forEach((c, i) => {
      const a = (i / Math.max(communities.length, 1)) * Math.PI * 2;
      centre.set(c, [Math.cos(a) * area * 0.28, Math.sin(a) * area * 0.28]);
    });

    const sim: SimNode[] = nodes.map((n) => {
      const [cx, cy] = centre.get(n.community ?? "·") ?? [0, 0];
      return {
        n,
        x: cx + (rand() - 0.5) * area * 0.2,
        y: cy + (rand() - 0.5) * area * 0.2,
        dx: 0,
        dy: 0,
        r: Math.min(3 + Math.sqrt(n.degree) * 1.3, 11),
      };
    });
    simRef.current = sim;
    byIdRef.current = new Map(sim.map((s) => [s.n.id, s]));
    tickRef.current = 0;
    userMovedRef.current = false;
  }, [nodes, edges]);

  // Fly the camera to an externally-focused node (search / inspector nav).
  useEffect(() => {
    if (focusId == null) return;
    const target = byIdRef.current.get(focusId);
    const canvas = canvasRef.current;
    if (!target || !canvas) return;
    camAnimRef.current = {
      from: { ...camRef.current },
      to: { x: target.x, y: target.y, scale: Math.max(camRef.current.scale, 1.6) },
      t0: performance.now(),
    };
  }, [focusId]);

  // ── Render + interaction loop (owns the layout ticks too) ─────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // One Fruchterman–Reingold tick over the sim in the refs.
    const tick = () => {
      const sim = simRef.current;
      const byId = byIdRef.current;
      if (sim.length === 0 || tickRef.current >= TICKS) return;
      const area = areaRef.current;
      const k = Math.sqrt((area * area) / sim.length);
      // Cooling: generous early movement, settling to stillness.
      const t = area * 0.1 * (1 - tickRef.current / TICKS) ** 2 + 0.5;

      for (const v of sim) {
        v.dx = 0;
        v.dy = 0;
      }
      // Repulsion (all pairs — the API caps nodes well below where this hurts).
      // Range-capped: beyond ~2.5k only gravity acts, so disconnected nodes
      // settle at the cluster's edge instead of being blasted into deep space.
      const cutoff2 = k * 2.5 * (k * 2.5);
      for (let i = 0; i < sim.length; i++) {
        const a = sim[i];
        for (let j = i + 1; j < sim.length; j++) {
          const b = sim[j];
          let ex = a.x - b.x;
          let ey = a.y - b.y;
          let d2 = ex * ex + ey * ey;
          if (d2 > cutoff2) continue;
          if (d2 < 0.01) {
            ex = 0.1;
            ey = 0.1;
            d2 = 0.02;
          }
          const d = Math.sqrt(d2);
          const f = (k * k) / d / d; // k²/d, normalized by d for the unit vector
          a.dx += ex * f;
          a.dy += ey * f;
          b.dx -= ex * f;
          b.dy -= ey * f;
        }
      }
      // Attraction along edges.
      for (const e of edges) {
        const a = byId.get(e.src);
        const b = byId.get(e.dst);
        if (!a || !b) continue;
        const ex = a.x - b.x;
        const ey = a.y - b.y;
        const d = Math.sqrt(ex * ex + ey * ey) || 0.1;
        const f = (d * d) / k / d;
        a.dx -= ex * f;
        a.dy -= ey * f;
        b.dx += ex * f;
        b.dy += ey * f;
      }
      // Gentle gravity to keep disconnected pieces on the map — stronger for
      // edge-less nodes, which have no attraction holding them anywhere.
      for (const v of sim) {
        const g = v.n.degree === 0 ? 0.1 : 0.03;
        v.dx -= v.x * g;
        v.dy -= v.y * g;
        const disp = Math.sqrt(v.dx * v.dx + v.dy * v.dy) || 0.1;
        const cap = Math.min(disp, t);
        v.x += (v.dx / disp) * cap;
        v.y += (v.dy / disp) * cap;
      }
      tickRef.current += 1;
    };

    const fitTarget = (): Camera | null => {
      const sim = simRef.current;
      if (sim.length === 0) return null;
      let minX = Infinity,
        maxX = -Infinity,
        minY = Infinity,
        maxY = -Infinity;
      for (const v of sim) {
        minX = Math.min(minX, v.x);
        maxX = Math.max(maxX, v.x);
        minY = Math.min(minY, v.y);
        maxY = Math.max(maxY, v.y);
      }
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const scale = Math.min(
        w / Math.max(maxX - minX + 120, 1),
        h / Math.max(maxY - minY + 120, 1),
        3.4,
      );
      return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, scale };
    };

    const fitView = () => {
      const t = fitTarget();
      if (t) camRef.current = t;
    };

    const draw = () => {
      const { selectedId: sel, dimCommunity: dim, communityColor: colors } = viewRef.current;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }

      // Progressive layout: several ticks per frame so it settles in ~2s.
      if (tickRef.current < TICKS) {
        for (let i = 0; i < 6 && tickRef.current < TICKS; i++) tick();
        if (!userMovedRef.current) fitView();
      }

      // Fit-view button: fly to the full-map framing.
      if (fitRequestRef.current) {
        fitRequestRef.current = false;
        const t = fitTarget();
        if (t) camAnimRef.current = { from: { ...camRef.current }, to: t, t0: performance.now() };
      }

      // Camera flight.
      const anim = camAnimRef.current;
      if (anim) {
        const p = Math.min((performance.now() - anim.t0) / 400, 1);
        const e = 1 - (1 - p) ** 5; // ease-out-quint
        camRef.current = {
          x: anim.from.x + (anim.to.x - anim.from.x) * e,
          y: anim.from.y + (anim.to.y - anim.from.y) * e,
          scale: anim.from.scale + (anim.to.scale - anim.from.scale) * e,
        };
        if (p >= 1) camAnimRef.current = null;
      }

      const cam = camRef.current;
      const toScreen = (x: number, y: number): [number, number] => [
        (x - cam.x) * cam.scale + w / 2,
        (y - cam.y) * cam.scale + h / 2,
      ];

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const sim = simRef.current;
      const byId = byIdRef.current;
      const hover = hoverRef.current;

      // Edges of the selected node draw amber on top of the neutral pass.
      ctx.lineWidth = 1;
      for (const e of edges) {
        const a = byId.get(e.src);
        const b = byId.get(e.dst);
        if (!a || !b) continue;
        const touchesSel = sel != null && (e.src === sel || e.dst === sel);
        const dimmed =
          (dim && a.n.community !== dim && b.n.community !== dim) ||
          (sel != null && !touchesSel);
        const [x1, y1] = toScreen(a.x, a.y);
        const [x2, y2] = toScreen(b.x, b.y);
        ctx.strokeStyle = touchesSel
          ? "oklch(0.84 0.165 91.3 / 0.55)"
          : `oklch(0.5 0.01 91.3 / ${dimmed ? 0.05 : e.confidence < 0.7 ? 0.1 : 0.18})`;
        ctx.setLineDash(EDGE_DASH[e.kind] ?? []);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Nodes.
      for (const v of sim) {
        const [x, y] = toScreen(v.x, v.y);
        if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
        const isSel = v.n.id === sel;
        const dimmed = dim ? v.n.community !== dim && !isSel : false;
        const color = colors.get(v.n.community ?? "·") ?? "hsl(0 0% 55%)";
        ctx.globalAlpha = dimmed ? 0.18 : 1;
        ctx.fillStyle = isSel ? "oklch(0.84 0.165 91.3)" : color;
        if (isSel) {
          // The one glow on the map — the selected node is "alive".
          ctx.shadowColor = "oklch(0.84 0.165 91.3 / 0.7)";
          ctx.shadowBlur = 16;
        }
        ctx.beginPath();
        ctx.arc(x, y, v.r * Math.min(cam.scale, 1.4), 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (v.n.annotations > 0 && !dimmed) {
          // Verified-findings tick: a small amber ring.
          ctx.strokeStyle = "oklch(0.84 0.165 91.3 / 0.8)";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(x, y, v.r * Math.min(cam.scale, 1.4) + 2.5, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (isSel || v === hover) {
          ctx.strokeStyle = "oklch(0.93 0.012 91.3 / 0.9)";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(x, y, v.r * Math.min(cam.scale, 1.4) + 4.5, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }

      // Labels once zoomed in (or for hovered/selected).
      ctx.font = "10px var(--font-plex-mono), monospace";
      ctx.textAlign = "center";
      for (const v of sim) {
        const show =
          v.n.id === sel || v === hover || (cam.scale > 1.35 && v.n.degree >= 3);
        if (!show) continue;
        const dimmed = dim ? v.n.community !== dim && v.n.id !== sel : false;
        if (dimmed) continue;
        const [x, y] = toScreen(v.x, v.y);
        if (x < 0 || y < 0 || x > w || y > h) continue;
        const short = v.n.fqname.split(".").slice(-1)[0] || v.n.fqname;
        ctx.fillStyle =
          v.n.id === sel ? "oklch(0.84 0.165 91.3)" : "oklch(0.65 0.015 91.3 / 0.9)";
        ctx.fillText(short, x, y - v.r * Math.min(cam.scale, 1.4) - 7);
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [edges]);

  // ── Pointer + wheel interactions ───────────────────────────────────────────
  const hitTest = useCallback((sx: number, sy: number): SimNode | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const cam = camRef.current;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const wx = (sx - w / 2) / cam.scale + cam.x;
    const wy = (sy - h / 2) / cam.scale + cam.y;
    let best: SimNode | null = null;
    let bestD = Infinity;
    for (const v of simRef.current) {
      const dx = v.x - wx;
      const dy = v.y - wy;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < v.r + 6 / cam.scale && d < bestD) {
        best = v;
        bestD = d;
      }
    }
    return best;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const pos = (e: PointerEvent | WheelEvent): [number, number] => {
      const r = canvas.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };

    const onDown = (e: PointerEvent) => {
      canvas.setPointerCapture(e.pointerId);
      const [x, y] = pos(e);
      dragRef.current = { x, y, moved: false };
    };
    const onMove = (e: PointerEvent) => {
      const [x, y] = pos(e);
      const drag = dragRef.current;
      if (drag) {
        const dx = x - drag.x;
        const dy = y - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        if (drag.moved) {
          const cam = camRef.current;
          cam.x -= dx / cam.scale;
          cam.y -= dy / cam.scale;
          drag.x = x;
          drag.y = y;
          userMovedRef.current = true;
          camAnimRef.current = null;
        }
      } else {
        hoverRef.current = hitTest(x, y);
        canvas.style.cursor = hoverRef.current ? "pointer" : "grab";
      }
    };
    const onUp = (e: PointerEvent) => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag && !drag.moved) {
        const [x, y] = pos(e);
        onSelect(hitTest(x, y)?.n.id ?? null);
      }
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [x, y] = pos(e);
      const cam = camRef.current;
      const factor = Math.exp(-e.deltaY * 0.0015);
      const next = Math.min(Math.max(cam.scale * factor, 0.2), 6);
      // Zoom about the cursor: keep the world point under it fixed.
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const wx = (x - w / 2) / cam.scale + cam.x;
      const wy = (y - h / 2) / cam.scale + cam.y;
      cam.x = wx - (x - w / 2) / next;
      cam.y = wy - (y - h / 2) / next;
      cam.scale = next;
      userMovedRef.current = true;
      camAnimRef.current = null;
    };
    const onLeave = () => {
      hoverRef.current = null;
    };

    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [hitTest, onSelect]);

  // Camera controls — animate to the new scale so zoom reads as movement.
  const zoomBy = useCallback((factor: number) => {
    const cam = camRef.current;
    camAnimRef.current = {
      from: { ...cam },
      to: { ...cam, scale: Math.min(Math.max(cam.scale * factor, 0.2), 6) },
      t0: performance.now(),
    };
    userMovedRef.current = true;
  }, []);

  const controlBtn =
    "pressable flex size-8 items-center justify-center text-muted transition-colors hover:bg-surface-3 hover:text-ink";

  return (
    <div className="relative h-full w-full">
      <canvas ref={canvasRef} className="h-full w-full" style={{ cursor: "grab" }} />
      <div className="absolute bottom-4 right-4 flex flex-col overflow-hidden rounded-md border border-border bg-surface-2">
        <button className={controlBtn} onClick={() => zoomBy(1.35)} aria-label="Zoom in" title="Zoom in">
          <Plus size={14} />
        </button>
        <button className={controlBtn} onClick={() => zoomBy(1 / 1.35)} aria-label="Zoom out" title="Zoom out">
          <Minus size={14} />
        </button>
        <button
          className={`${controlBtn} border-t border-border`}
          onClick={() => {
            fitRequestRef.current = true;
          }}
          aria-label="Fit view"
          title="Fit view"
        >
          <CornersOut size={14} />
        </button>
      </div>
    </div>
  );
}
