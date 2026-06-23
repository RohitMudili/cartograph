"use client";

/**
 * Agent roster — the left rail of Mission Control. One card per agent in the
 * fleet (planner, the parallel explorers, synthesizer, critic, librarian),
 * showing role glyph, state dot (working pulses amber, done = green check,
 * failed = red), current activity, and live tool/finding counts. Pure render of
 * the reduced RunState (DESIGN.md "instrument panel").
 */

import {
  BookOpen,
  CheckCircle,
  MagnifyingGlass,
  ShieldCheck,
  Stack,
  Strategy,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react";

import type { AgentCard } from "@/lib/runState";

const ROLE_ICON: Record<string, Icon> = {
  planner: Strategy,
  explorer: MagnifyingGlass,
  synthesizer: Stack,
  critic: ShieldCheck,
  librarian: BookOpen,
};

function StateDot({ state }: { state: AgentCard["state"] }) {
  if (state === "done")
    return <CheckCircle weight="fill" size={14} className="text-verified" />;
  if (state === "failed")
    return <WarningCircle weight="fill" size={14} className="text-rejected" />;
  if (state === "working")
    return (
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
      </span>
    );
  return <span className="h-2.5 w-2.5 rounded-full bg-faint/50" />;
}

function RosterCard({ card }: { card: AgentCard }) {
  const Glyph = ROLE_ICON[card.role] ?? MagnifyingGlass;
  const live = card.state === "working";
  return (
    <div
      className={`rounded-lg border bg-surface/60 px-3 py-2.5 transition-colors ${
        live ? "border-primary/40" : "border-border"
      }`}
      style={live ? { boxShadow: "var(--glow-live)" } : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <Glyph weight="duotone" size={16} className="shrink-0 text-muted" />
          <span className="truncate text-sm text-ink" title={card.label}>
            {card.label}
          </span>
        </span>
        <StateDot state={card.state} />
      </div>
      <p className="mt-1.5 truncate font-mono text-xs text-faint" title={card.activity}>
        {card.activity || "idle"}
      </p>
      {(card.toolCalls > 0 || card.findings > 0) && (
        <div className="mt-1.5 flex gap-3 font-mono text-[0.7rem] text-muted tabular">
          {card.toolCalls > 0 && <span>{card.toolCalls} tools</span>}
          {card.findings > 0 && <span>{card.findings} findings</span>}
        </div>
      )}
    </div>
  );
}

export function AgentRoster({ agents }: { agents: AgentCard[] }) {
  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto p-3">
      <p className="px-1 pb-1 font-mono text-[0.7rem] uppercase tracking-[0.18em] text-faint">
        Agents
      </p>
      {agents.length === 0 ? (
        <p className="px-1 text-sm text-faint">Waiting for the planner…</p>
      ) : (
        agents.map((c) => <RosterCard key={c.key} card={c} />)
      )}
    </div>
  );
}
