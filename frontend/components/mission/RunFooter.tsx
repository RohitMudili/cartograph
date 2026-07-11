"use client";

/**
 * Run footer — the telemetry strip. Phase progress (static → planning →
 * exploring → synthesis → critique → writing → done), live counters (findings,
 * accepted/rejected, annotations, tokens) and a mono cost ticker. Mono numerals
 * with tabular-nums so values don't jitter as they tick (DESIGN.md).
 */

import type { RunPhase, RunState } from "@/lib/runState";

const PHASE_ORDER: RunPhase[] = [
  "planning",
  "exploring",
  "synthesis",
  "critique",
  "writing",
  "done",
];

const PHASE_LABEL: Record<RunPhase, string> = {
  starting: "starting",
  cloning: "cloning",
  parsing: "parsing",
  summarizing: "summarizing",
  communities: "communities",
  planning: "planning",
  exploring: "exploring",
  synthesis: "synthesis",
  critique: "critique",
  writing: "writing",
  done: "done",
  error: "error",
};

function Stat({ label, value, tone = "ink" }: { label: string; value: string; tone?: string }) {
  const color =
    tone === "amber" ? "text-primary" : tone === "muted" ? "text-muted" : "text-ink";
  return (
    <div className="flex flex-col">
      <span className={`font-mono text-sm tabular ${color}`}>{value}</span>
      <span className="font-mono text-[0.65rem] uppercase tracking-wide text-faint">{label}</span>
    </div>
  );
}

export function RunFooter({ state }: { state: RunState }) {
  const activeIdx = PHASE_ORDER.indexOf(state.phase);
  const { totals } = state;
  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-border bg-surface-2/40 px-5 py-3">
      {/* phase pipeline */}
      <div className="flex items-center gap-1.5">
        {PHASE_ORDER.map((p, i) => {
          const done = state.phase === "done" || (activeIdx >= 0 && i < activeIdx);
          const active = p === state.phase;
          return (
            <div key={p} className="flex items-center gap-1.5">
              <span
                className={`font-mono text-[0.7rem] ${
                  active ? "text-primary" : done ? "text-muted" : "text-faint"
                }`}
              >
                {active && state.phase !== "done" ? `▸ ${PHASE_LABEL[p]}` : PHASE_LABEL[p]}
              </span>
              {i < PHASE_ORDER.length - 1 && <span className="text-faint">·</span>}
            </div>
          );
        })}
        {state.phase === "error" && (
          <span className="ml-2 font-mono text-[0.7rem] text-rejected">error</span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-8">
        <Stat label="findings" value={String(totals.findings)} />
        <Stat label="verified" value={String(totals.accepted)} tone="muted" />
        <Stat label="rejected" value={String(totals.rejected)} tone="muted" />
        <Stat label="annotations" value={String(totals.annotations)} />
        <Stat
          label="tokens"
          value={(totals.inputTokens + totals.outputTokens).toLocaleString()}
          tone="muted"
        />
        <Stat
          label="cost"
          value={totals.usd != null ? `$${totals.usd.toFixed(4)}` : "—"}
          tone="amber"
        />
      </div>
    </div>
  );
}
