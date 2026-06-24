/**
 * Pure reducer: agent events → the Mission Control view model.
 *
 * `reduceRun(events)` is a pure function of the event list, so it produces the
 * exact same state whether events arrive live over the WebSocket or are replayed
 * from the durable log through a scrubber. Mission Control renders this state and
 * nothing else — no view computes its own status (the architectural rule from
 * FRONTEND.md §4/§6).
 */

import type { AgentEvent, AgentRole } from "./events";

export type AgentState = "idle" | "working" | "done" | "failed";
export type RunPhase =
  | "starting"
  | "cloning"
  | "parsing"
  | "summarizing"
  | "planning"
  | "exploring"
  | "synthesis"
  | "critique"
  | "writing"
  | "done"
  | "error";

/** The pre-fleet pipeline phases, shown as an intro before the agents appear. */
export const PIPELINE_PHASES: RunPhase[] = ["cloning", "parsing", "summarizing"];

export interface AgentCard {
  /** Stable key: role, or `explorer:<subsystem>` for the parallel explorers. */
  key: string;
  role: AgentRole | string;
  label: string; // human label (subsystem name for explorers)
  state: AgentState;
  activity: string; // one-line current activity (e.g. "read_file core.py")
  toolCalls: number;
  findings: number;
}

export interface FeedRow {
  seq: number;
  agent: AgentRole | string;
  type: string;
  /** Pre-formatted, render-ready fields. */
  label: string; // owning agent/subsystem
  text: string; // the finding/verdict/phase text
  target?: string; // fqname for findings/verdicts
  accepted?: boolean; // for verdicts
  revised?: boolean;
}

export interface RunState {
  phase: RunPhase;
  agents: AgentCard[];
  feed: FeedRow[];
  /** fqnames touched by explorers (tool calls / findings) — lights up the graph. */
  touched: Set<string>;
  verified: Set<string>; // fqnames with an accepted verdict
  totals: {
    findings: number;
    accepted: number;
    rejected: number;
    annotations: number;
    inputTokens: number;
    outputTokens: number;
    usd: number | null;
  };
  /** True once the supervisor emits its terminal done/error. */
  finished: boolean;
  error: string | null;
  /** Set on the terminal event — drives the finish panel. */
  terminal: {
    ok: boolean; // the index reached INDEXED (vs a hard clone/parse error)
    enriched: boolean; // the agent fleet actually wrote findings
    enrichmentError: string | null; // why the fleet was skipped/throttled, if any
    nodes: number;
    annotations: number;
  } | null;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

function emptyState(): RunState {
  return {
    phase: "starting",
    agents: [],
    feed: [],
    touched: new Set(),
    verified: new Set(),
    totals: {
      findings: 0,
      accepted: 0,
      rejected: 0,
      annotations: 0,
      inputTokens: 0,
      outputTokens: 0,
      usd: null,
    },
    finished: false,
    error: null,
    terminal: null,
  };
}

/** Find-or-create the roster card for an event, keyed by label for explorers. */
function cardKey(agent: string, payload: Record<string, unknown>): string {
  const label = str(payload.label);
  if (agent === "explorer" && label) return label; // e.g. "explorer:auth"
  return agent;
}

function ensureCard(map: Map<string, AgentCard>, agent: string, payload: Record<string, unknown>) {
  const key = cardKey(agent, payload);
  let card = map.get(key);
  if (!card) {
    const label = str(payload.label || payload.subsystem) || agent;
    card = { key, role: agent, label, state: "idle", activity: "", toolCalls: 0, findings: 0 };
    map.set(key, card);
  }
  return card;
}

const PHASES: Record<string, RunPhase> = {
  cloning: "cloning",
  parsing: "parsing",
  summarizing: "summarizing",
  planning: "planning",
  exploring: "exploring",
  synthesis: "synthesis",
  critique: "critique",
  writing: "writing",
};

/** Fold an ordered event list into the render-ready RunState. */
export function reduceRun(events: AgentEvent[]): RunState {
  const s = emptyState();
  const cards = new Map<string, AgentCard>();

  for (const e of events) {
    const p = e.payload ?? {};
    const agent = str(e.agent);

    switch (e.type) {
      case "phase": {
        const phase = PHASES[str(p.phase)];
        if (phase) s.phase = phase;
        break;
      }
      case "spawn": {
        if (agent === "supervisor") break;
        const card = ensureCard(cards, agent, p);
        card.state = "working";
        card.activity = agent === "explorer" ? "exploring" : "thinking";
        break;
      }
      case "tool_call": {
        const card = ensureCard(cards, agent, p);
        card.toolCalls += 1;
        card.activity = `${str(p.tool)}(${str(p.arg)})`.slice(0, 48);
        if (p.arg) s.touched.add(str(p.arg));
        s.feed.push({
          seq: e.seq,
          agent,
          type: "tool_call",
          label: str(p.label) || agent,
          text: `${str(p.tool)} ${str(p.arg)}`,
        });
        break;
      }
      case "finding": {
        const card = ensureCard(cards, agent, p);
        card.findings += 1;
        s.totals.findings += 1;
        const target = str(p.target);
        if (target) s.touched.add(target);
        s.feed.push({
          seq: e.seq,
          agent,
          type: "finding",
          label: str(p.label || p.subsystem) || agent,
          text: str(p.text),
          target,
        });
        break;
      }
      case "verdict": {
        const accepted = p.accepted === true;
        const target = str(p.target);
        if (accepted) {
          s.totals.accepted += 1;
          if (target) s.verified.add(target);
        } else {
          s.totals.rejected += 1;
        }
        s.feed.push({
          seq: e.seq,
          agent: "critic",
          type: "verdict",
          label: "critic",
          text: str(p.reason || p.text),
          target,
          accepted,
          revised: p.revised === true,
        });
        break;
      }
      case "done": {
        if (agent === "supervisor") {
          s.totals.annotations = Number(p.annotations ?? s.totals.annotations) || s.totals.annotations;
          s.totals.inputTokens = Number(p.input_tokens ?? 0) || s.totals.inputTokens;
          s.totals.outputTokens = Number(p.output_tokens ?? 0) || s.totals.outputTokens;
          if (typeof p.usd === "number") s.totals.usd = p.usd;
          // The pipeline's terminal event (terminal:true) finishes the run; the
          // fleet's own internal "done" is not terminal (the index continues).
          if (p.terminal === true) {
            s.finished = true;
            s.phase = "done";
            s.terminal = {
              ok: true,
              enriched: p.enriched === true,
              enrichmentError: p.enrichment_error ? str(p.enrichment_error) : null,
              nodes: Number(p.nodes ?? 0) || 0,
              annotations: Number(p.annotations ?? 0) || 0,
            };
          }
        } else {
          const card = ensureCard(cards, agent, p);
          card.state = "done";
          card.activity = "done";
          if (agent === "librarian") {
            s.totals.annotations = Number(p.annotations ?? s.totals.annotations) || s.totals.annotations;
          }
        }
        break;
      }
      case "error": {
        if (agent === "supervisor" && p.terminal === true) {
          // Hard failure (clone/parse) — the index itself failed.
          s.finished = true;
          s.phase = "error";
          s.error = str(p.error) || "indexing failed";
          s.terminal = {
            ok: false,
            enriched: false,
            enrichmentError: str(p.error) || null,
            nodes: 0,
            annotations: 0,
          };
        } else if (agent === "supervisor") {
          // Non-terminal: the agent fleet errored/throttled, but the index still
          // completes on the static + summary layers. Record it for the finish panel.
          s.error = s.error ?? (str(p.error) || "agent enrichment failed");
        } else {
          const card = ensureCard(cards, agent, p);
          card.state = "failed";
          card.activity = str(p.error).slice(0, 48) || "failed";
        }
        break;
      }
    }
  }

  // When the run is finished, any still-"working" card settled (done).
  if (s.finished) {
    for (const c of cards.values()) {
      if (c.state === "working") c.state = "done";
    }
  }

  // Roster order: planner, explorers (by label), synthesizer, critic, librarian.
  const order = (c: AgentCard) => {
    const rank: Record<string, number> = {
      planner: 0,
      explorer: 1,
      synthesizer: 2,
      critic: 3,
      librarian: 4,
    };
    return rank[c.role] ?? 9;
  };
  s.agents = [...cards.values()].sort(
    (a, b) => order(a) - order(b) || a.label.localeCompare(b.label),
  );
  // Newest feed rows first.
  s.feed.reverse();
  return s;
}
