/**
 * Agent-event stream client for Mission Control (backend PLAN.md §4.3).
 *
 * One event shape, two sources — replay (the durable agent_events log via
 * `?after_seq=`) and live (the WebSocket). Both feed the SAME reducer
 * (lib/runState), so the UI renders identically whether it's watching a run
 * happen or replaying a recorded one. That's the "replay-first" architecture:
 * build and demo against recorded logs, then the live fleet drops in unchanged.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Who emitted an event (mirrors backend AgentRole). */
export type AgentRole =
  | "planner"
  | "explorer"
  | "synthesizer"
  | "critic"
  | "librarian"
  | "supervisor";

/** What an event records (mirrors backend AgentEventType). */
export type AgentEventType =
  | "spawn"
  | "tool_call"
  | "finding"
  | "verdict"
  | "phase"
  | "error"
  | "done";

export interface AgentEvent {
  seq: number;
  run_id: string;
  agent: AgentRole | string;
  type: AgentEventType | string;
  payload: Record<string, unknown>;
  ts: string | null;
}

/** Fetch all persisted events for a run after `afterSeq` (replay/backfill). */
export async function fetchRunEvents(
  repoId: string,
  runId: string,
  afterSeq = 0,
): Promise<AgentEvent[]> {
  const res = await fetch(
    `${API_URL}/api/repos/${repoId}/runs/${runId}/events?after_seq=${afterSeq}`,
  );
  if (!res.ok) {
    throw new Error(`failed to load events (${res.status})`);
  }
  return (await res.json()) as AgentEvent[];
}

/** WebSocket URL for the live stream (http(s) → ws(s)). */
export function runEventsWsUrl(repoId: string, runId: string, afterSeq = 0): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/api/repos/${repoId}/runs/${runId}/events/ws?after_seq=${afterSeq}`;
}
