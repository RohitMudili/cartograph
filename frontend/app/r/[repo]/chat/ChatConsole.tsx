"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button, RouteBadge, Spinner, StatusChip, VerifyBadge } from "@/components/ui";
import { type AnswerResponse, ApiError, type Repo, api } from "@/lib/api";

interface Thread {
  id: number;
  question: string;
  answer: AnswerResponse | null;
  error: string | null;
  pending: boolean;
}

export function ChatConsole({ repoId }: { repoId: string }) {
  const [repo, setRepo] = useState<Repo | null>(null);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load repo, and poll while it's still indexing so the UI reflects progress.
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const r = await api.getRepo(repoId);
        if (!active) return;
        setRepo(r);
        if (r.status !== "indexed" && r.status !== "failed") {
          timer = setTimeout(poll, 1500);
        }
      } catch (e) {
        if (active) setRepoError(e instanceof ApiError ? e.detail : "Repo not found.");
      }
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [repoId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [threads]);

  const ready = repo?.status === "indexed";

  async function ask() {
    const q = draft.trim();
    if (!q || !ready) return;
    const id = nextId.current++;
    setThreads((t) => [...t, { id, question: q, answer: null, error: null, pending: true }]);
    setDraft("");
    try {
      const answer = await api.ask(repoId, q);
      setThreads((t) => t.map((th) => (th.id === id ? { ...th, answer, pending: false } : th)));
    } catch (e) {
      const msg = e instanceof ApiError ? e.detail : "The request failed.";
      setThreads((t) => t.map((th) => (th.id === id ? { ...th, error: msg, pending: false } : th)));
    }
  }

  const repoName = repo?.url.replace(/^https?:\/\/github\.com\//, "") ?? "…";

  return (
    <div className="flex h-dvh flex-col bg-bg">
      {/* top bar */}
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link href="/" className="flex items-center gap-2 text-sm text-muted hover:text-ink">
          <span className="text-primary" aria-hidden>
            ◆
          </span>
          <span className="font-mono uppercase tracking-widest">Cartograph</span>
        </Link>
        <span className="text-faint">/</span>
        <span className="truncate font-mono text-sm text-ink">{repoName}</span>
        {repo && <StatusChip status={repo.status} />}
        {repo?.stats?.nodes != null && repo.status === "indexed" && (
          <span className="ml-auto font-mono text-xs text-faint tabular">
            {repo.stats.nodes} nodes · {repo.stats.edges} edges
          </span>
        )}
      </header>

      {/* conversation */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-8">
          {repoError && (
            <p className="rounded-md border border-rejected/40 bg-surface-2 px-4 py-3 text-sm text-rejected">
              {repoError}
            </p>
          )}

          {repo && !ready && repo.status !== "failed" && (
            <div className="flex items-center gap-2 text-sm text-pending" role="status">
              <Spinner className="border-pending/60 border-t-pending" />
              Indexing {repoName} — you can ask questions once it&apos;s ready.
            </div>
          )}

          {repo?.status === "failed" && (
            <p className="rounded-md border border-rejected/40 bg-surface-2 px-4 py-3 text-sm text-rejected">
              Indexing failed for this repo.
            </p>
          )}

          {ready && threads.length === 0 && <EmptyState onPick={setDraft} />}

          <div className="space-y-8">
            {threads.map((th) => (
              <ThreadBlock key={th.id} thread={th} />
            ))}
          </div>
        </div>
      </div>

      {/* composer */}
      <div className="shrink-0 border-t border-border bg-surface-2/40">
        <div className="mx-auto flex max-w-3xl items-end gap-3 px-6 py-4">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
            disabled={!ready}
            rows={1}
            placeholder={
              ready ? "Ask about this codebase…" : "Waiting for indexing to finish…"
            }
            className="max-h-40 flex-1 resize-none rounded-md border border-border bg-surface px-4 py-2.5 text-sm text-ink placeholder:text-faint focus:border-border-hi disabled:opacity-50"
            aria-label="Ask a question about the repository"
          />
          <Button onClick={ask} disabled={!ready || !draft.trim()}>
            Ask
          </Button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  const examples = [
    "What does this repo do?",
    "How is the main data structure implemented?",
    "Where does input validation happen?",
  ];
  return (
    <div className="rounded-lg border border-border bg-surface/40 p-6">
      <p className="text-sm text-muted">
        Ask a question about this codebase. Answers are grounded in the indexed source,
        with citations verified against the real{" "}
        <span className="font-mono text-ink">file:line</span>.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {examples.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-sm border border-border bg-surface-2 px-3 py-1.5 text-xs text-muted hover:border-border-hi hover:text-ink"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function ThreadBlock({ thread }: { thread: Thread }) {
  return (
    <div>
      {/* question — right-aligned, quiet */}
      <div className="mb-3 flex justify-end">
        <div className="max-w-[80%] rounded-lg rounded-tr-sm border border-border bg-surface-2 px-4 py-2 text-sm text-ink">
          {thread.question}
        </div>
      </div>

      {thread.pending && (
        <div className="flex items-center gap-2 text-sm text-muted" role="status">
          <Spinner /> Searching the graph and verifying citations…
        </div>
      )}

      {thread.error && (
        <p className="rounded-md border border-rejected/40 bg-surface-2 px-4 py-2.5 text-sm text-rejected">
          {thread.error}
        </p>
      )}

      {thread.answer && <AnswerBlock answer={thread.answer} />}
    </div>
  );
}

function AnswerBlock({ answer }: { answer: AnswerResponse }) {
  if (!answer.answerable) {
    return (
      <div className="rounded-lg border border-border bg-surface/40 px-4 py-3 text-sm text-muted">
        {answer.answer}
      </div>
    );
  }
  const verifiedCount = answer.citations.filter((c) => c.verified).length;
  return (
    <div className="rounded-lg border border-border bg-surface/40">
      <div className="whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed text-ink">
        {answer.answer}
      </div>

      {answer.citations.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border px-4 py-3">
          {answer.citations.map((c, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-xs ${
                c.verified
                  ? "border-primary/30 bg-[var(--primary-dim)] text-primary"
                  : "border-rejected/40 text-rejected line-through decoration-rejected/60"
              }`}
              title={
                c.verified
                  ? "Verified against the indexed source"
                  : "This citation could not be verified — treat the claim as unverified"
              }
            >
              <VerifyBadge verified={c.verified} />
              {c.path}:{c.start_line}
              {c.end_line !== c.start_line ? `-${c.end_line}` : ""}
            </span>
          ))}
        </div>
      )}

      {/* transparency strip — the signature element */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 font-mono text-xs text-faint tabular">
        <span className="flex items-center gap-1.5">
          route <RouteBadge route={answer.route} />
        </span>
        <span>
          {verifiedCount}/{answer.citations.length} citations verified
        </span>
        <span>{answer.used_nodes.length} nodes consulted</span>
        {answer.fully_verified && answer.citations.length > 0 && (
          <span className="flex items-center gap-1 text-verified">
            <span aria-hidden>✓</span> fully verified
          </span>
        )}
      </div>
    </div>
  );
}
