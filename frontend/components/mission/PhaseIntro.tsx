"use client";

/**
 * Pre-fleet intro. While the pipeline clones, parses, and summarizes (before the
 * agents spawn), this overlays the map area with a calm phase sequence so the
 * page isn't an empty grid. Each phase lights up as it's reached; completed ones
 * settle to a check. Smooth, no spinner-soup.
 */

import { CheckCircle } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

import { PIPELINE_PHASES, type RunPhase } from "@/lib/runState";

const LABELS: Record<string, string> = {
  cloning: "Cloning the repository",
  parsing: "Parsing the code into a graph",
  summarizing: "Summarizing & embedding symbols",
  communities: "Detecting code communities",
};

// Phases that come after the intro — once we're here, the intro phases are done.
const FLEET_PHASES = new Set<RunPhase>([
  "planning",
  "exploring",
  "synthesis",
  "critique",
  "writing",
  "done",
]);

export function PhaseIntro({ phase }: { phase: RunPhase }) {
  const reduce = useReducedMotion();
  const order = PIPELINE_PHASES;
  const activeIdx = order.indexOf(phase);
  // If we've moved past the pipeline into fleet phases, treat all intro phases done.
  const idx = FLEET_PHASES.has(phase) ? order.length : activeIdx;

  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <div className="w-full max-w-xs px-6">
        <p className="mb-5 text-center font-mono text-[0.7rem] uppercase tracking-[0.2em] text-faint">
          Mapping your codebase
        </p>
        <ul className="space-y-3">
          {order.map((p, i) => {
            const done = idx > i || idx === order.length;
            const active = idx === i;
            return (
              <li key={p} className="flex items-center gap-3">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                  {done ? (
                    <CheckCircle weight="fill" size={18} className="text-verified" />
                  ) : active ? (
                    <span className="relative flex h-2.5 w-2.5">
                      {!reduce && (
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60" />
                      )}
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
                    </span>
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-faint/40" />
                  )}
                </span>
                <span
                  className={`text-sm transition-colors ${
                    active ? "text-ink" : done ? "text-muted" : "text-faint"
                  }`}
                >
                  {LABELS[p] ?? p}
                </span>
              </li>
            );
          })}
        </ul>
        <AnimatePresence>
          {idx >= order.length && (
            <motion.p
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="mt-5 text-center font-mono text-xs text-primary"
            >
              agents spawning…
            </motion.p>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
