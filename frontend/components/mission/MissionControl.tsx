"use client";

/**
 * Mission Control — the live (and replayable) view of the agent fleet mapping a
 * repo. Resolves the repo's latest index run, streams its agent events
 * (useRunEvents), folds them into a render-ready RunState (reduceRun), and lays
 * the fleet out: roster (left) · territory graph (center) · findings feed (right),
 * over a replay scrubber + telemetry footer.
 *
 * Replay-first: a finished run defaults to REPLAY (plays back from the recorded
 * log); a run still in progress defaults to LIVE (WebSocket). Same reducer + same
 * components either way — the UI can't tell the difference.
 */

import { Graph } from "@phosphor-icons/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { type Repo, api } from "@/lib/api";
import { reduceRun } from "@/lib/runState";
import { useRunEvents } from "@/lib/useRunEvents";

import { AgentRoster } from "./AgentRoster";
import { FindingsFeed } from "./FindingsFeed";
import { FinishPanel } from "./FinishPanel";
import { PhaseIntro } from "./PhaseIntro";
import { ReplayScrubber } from "./ReplayScrubber";
import { RunFooter } from "./RunFooter";

// Three.js stays off SSR / the initial bundle (loaded only when the view mounts).
const TerritoryGraph = dynamic(
  () => import("./TerritoryGraph").then((m) => m.TerritoryGraph),
  { ssr: false, loading: () => <div className="h-full w-full" aria-hidden /> },
);

const ACTIVE_STATUSES = new Set(["cloning", "parsing", "summarizing", "enriching", "pending"]);

export function MissionControl({ repoId }: { repoId: string }) {
  const [repo, setRepo] = useState<Repo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getRepo(repoId)
      .then((r) => !cancelled && setRepo(r))
      .catch(() => !cancelled && setError("Couldn't load this repo. Is the backend running?"));
    return () => {
      cancelled = true;
    };
  }, [repoId]);

  const runId = repo?.latest_run_id ?? null;
  // A run still indexing → watch live; a finished one → replay it.
  const initialMode = repo && ACTIVE_STATUSES.has(repo.status) ? "live" : "replay";
  const handle = useRunEvents(repo ? repoId : null, runId, initialMode);
  const state = useMemo(() => reduceRun(handle.events), [handle.events]);
  const touched = useMemo(() => [...state.touched], [state.touched]);

  // Re-trigger indexing (e.g. after the agent pass was throttled). Sends them back
  // to a fresh live run.
  async function retryEnrichment() {
    try {
      const r = await api.indexRepo(repo!.url);
      window.location.href = r.already_indexed ? `/r/${r.repo_id}/chat` : `/r/${r.repo_id}/run`;
    } catch {
      /* surfaced by the run itself */
    }
  }

  if (error) {
    return <CenterNote title="Mission Control">{error}</CenterNote>;
  }
  if (!repo) {
    return <CenterNote title="Mission Control">Loading run…</CenterNote>;
  }
  if (!runId) {
    return (
      <CenterNote title="Mission Control">
        This repo has no run yet. Index it from the home page to watch the agent
        fleet map it.
      </CenterNote>
    );
  }

  // Before the fleet appears (cloning/parsing/summarizing, no agents yet), show a
  // calm phase intro instead of an empty roster/graph.
  const preFleet = state.agents.length === 0 && !state.finished;

  return (
    <main className="flex h-[100dvh] flex-col bg-bg text-ink">
      <Header repoId={repoId} url={repo.url} />
      <div className="relative grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[clamp(220px,20vw,300px)_1fr_clamp(300px,28vw,420px)]">
        <aside className="hidden min-h-0 border-r border-border lg:block">
          <AgentRoster agents={state.agents} />
        </aside>
        <section className="relative min-h-0 border-border max-lg:border-b">
          <TerritoryGraph touched={touched} verified={state.verified} />
          {preFleet && <PhaseIntro phase={state.phase} />}
        </section>
        <aside className="min-h-0 border-l border-border">
          <FindingsFeed feed={state.feed} />
        </aside>

        {state.terminal && (
          <FinishPanel repoId={repoId} state={state} onRetry={retryEnrichment} />
        )}
      </div>
      <ReplayScrubber handle={handle} />
      <RunFooter state={state} />
    </main>
  );
}

function Header({ repoId, url }: { repoId: string; url: string }) {
  const name = url.replace(/^https?:\/\/(www\.)?github\.com\//, "").replace(/\.git$/, "");
  return (
    <header className="flex items-center justify-between border-b border-border px-5 py-3">
      <div className="flex items-center gap-2.5">
        <Graph weight="bold" size={18} className="text-primary" />
        <span className="font-mono text-sm uppercase tracking-[0.18em]">Mission Control</span>
        <span className="font-mono text-xs text-faint">{name}</span>
      </div>
      <Link
        href={`/r/${repoId}/chat`}
        className="text-sm text-muted transition-colors hover:text-ink"
      >
        Ask a question →
      </Link>
    </header>
  );
}

function CenterNote({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="flex h-[100dvh] flex-col items-center justify-center gap-3 bg-bg px-6 text-center text-ink">
      <span className="flex items-center gap-2 font-mono text-sm uppercase tracking-[0.18em] text-muted">
        <Graph weight="bold" size={16} className="text-primary" />
        {title}
      </span>
      <p className="max-w-sm text-sm text-muted">{children}</p>
    </main>
  );
}
