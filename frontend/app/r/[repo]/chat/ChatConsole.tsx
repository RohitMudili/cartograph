"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AuthMenu } from "@/components/auth/AuthMenu";
import { Button, RouteBadge, Spinner, StatusChip, VerifyBadge } from "@/components/ui";
import {
  type AnswerResponse,
  ApiError,
  type Repo,
  type SessionSummary,
  api,
} from "@/lib/api";

interface Thread {
  id: number;
  question: string;
  answer: AnswerResponse | null;
  conversation_id: string | null;
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

  // Session state
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Load repo, and poll while it's still indexing
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const r = await api.getRepo(repoId);
        if (!active) return;
        setRepo(r);
        setRepoError(null); // clear any previous "Not Found" error
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

  // Load sessions on mount and when repo is ready
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const list = await api.listSessions(repoId);
        if (!active) return;
        setSessions(list);
      } catch {
        // sessions may fail silently if user is not signed in
      } finally {
        if (active) setSessionsLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [repoId]);

  // Create a new session and set it as active.
  async function newSession() {
    try {
      const { session_id } = await api.createSession(repoId);
      setActiveSessionId(session_id);
      setThreads([]);
      setSidebarOpen(false);
      // Refresh the sessions list after creating
      const list = await api.listSessions(repoId);
      setSessions(list);
    } catch {
      // silently fail
    }
  }

  // Switch to an existing session
  async function switchSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setThreads([]);
    setSidebarOpen(false);
    try {
      const questions = await api.listQuestions(repoId, sessionId);
      // Reverse to show oldest first (chronological order)
      const loadedThreads: Thread[] = questions
        .slice()
        .reverse()
        .map((q) => ({
          id: nextId.current++,
          question: q.text,
          answer: {
            question: q.text,
            answer: q.answer.text,
            route: q.route,
            answerable: q.answer.answerable,
            fully_verified: q.citation_verified,
            citations: q.citations.map((c) => ({
              path: c.path,
              start_line: c.start_line,
              end_line: c.end_line,
              verified: c.verified,
            })),
            used_nodes: [],
            session_id: q.session_id ?? "",
            conversation_id: q.conversation_id ?? "",
          },
          conversation_id: q.conversation_id ?? null,
          error: null,
          pending: false,
        }));
      setThreads(loadedThreads);
    } catch {
      // silently fail
    }
  }

  // Auto-create a session on first mount if none is active. `newSession` is
  // async (setState runs after the await), so this is a network side-effect, not
  // a synchronous render-driven update; it intentionally fires only on the gate
  // conditions, not on newSession's identity.
  useEffect(() => {
    if (!sessionsLoading && !activeSessionId && repo?.status === "indexed") {
      // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps -- async network call; setState runs after await; intentionally fires on gate conditions only
      void newSession();
    }
  }, [sessionsLoading, activeSessionId, repo?.status]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [threads]);

  const ready = repo?.status === "indexed";

  async function ask() {
    const q = draft.trim();
    if (!q || !ready) return;
    const id = nextId.current++;
    setThreads((t) => [...t, { id, question: q, answer: null, conversation_id: null, error: null, pending: true }]);
    setDraft("");
    try {
      const answer = await api.ask(repoId, q, activeSessionId ?? undefined);
      // Use the session_id returned by the backend — it may have been auto-created.
      setActiveSessionId(answer.session_id);
      setThreads((t) =>
        t.map((th) =>
          th.id === id
            ? { ...th, answer, conversation_id: answer.conversation_id, pending: false }
            : th,
        ),
      );
      // Refresh sessions list to update preview/message count
      const list = await api.listSessions(repoId);
      setSessions(list);
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
        {/* hamburger — visible on small screens */}
        <button
          onClick={() => setSidebarOpen((o) => !o)}
          className="flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-ink sm:hidden"
          aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
        >
          {sidebarOpen ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          )}
        </button>

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
          <span className="hidden font-mono text-xs text-faint tabular sm:inline">
            {repo.stats.nodes} nodes · {repo.stats.edges} edges
          </span>
        )}
        <span className="ml-auto" />
        <Link
          href="/repos"
          className="hidden text-sm text-muted transition-colors hover:text-ink sm:inline"
        >
          My repos
        </Link>
        <AuthMenu />
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* session sidebar */}
        <aside
          className={`flex w-64 shrink-0 flex-col border-r border-border bg-surface-2/60 transition-all sm:flex ${
            sidebarOpen ? "absolute inset-y-14 left-0 z-50 w-64 sm:relative sm:inset-auto" : "hidden"
          }`}
        >
          {/* new chat button */}
          <div className="shrink-0 border-b border-border p-3">
            <Button
              onClick={newSession}
              className="w-full justify-center gap-2 px-3 py-1.5 text-xs"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              New chat
            </Button>
          </div>

          {/* session list */}
          <nav className="flex-1 space-y-1 overflow-y-auto p-2" aria-label="Chat sessions">
            {sessionsLoading && (
              <div className="flex justify-center py-6">
                <Spinner className="size-4 border-faint/60 border-t-muted" />
              </div>
            )}

            {!sessionsLoading && sessions.length === 0 && (
              <p className="px-2 text-center text-xs text-faint">
                No previous sessions. Start a new chat.
              </p>
            )}

            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => switchSession(s.id)}
                className={`w-full rounded-md px-3 py-2 text-left text-xs transition-colors ${
                  s.id === activeSessionId
                    ? "bg-primary/10 text-primary ring-1 ring-primary/30"
                    : "text-muted hover:bg-surface-2 hover:text-ink"
                }`}
              >
                <div className="truncate font-medium">
                  {s.preview || "Untitled session"}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-faint tabular">
                  <span>{s.message_count} {s.message_count === 1 ? "message" : "messages"}</span>
                  {s.last_activity && (
                    <span>{formatRelativeTime(s.last_activity)}</span>
                  )}
                </div>
              </button>
            ))}
          </nav>

          {/* session count footer */}
          {sessions.length > 0 && (
            <div className="shrink-0 border-t border-border px-3 py-2 text-[10px] text-faint">
              {sessions.length} session{sessions.length !== 1 ? "s" : ""}
            </div>
          )}
        </aside>

        {/* overlay backdrop on mobile */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/40 sm:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* conversation area */}
        <div className="flex flex-1 flex-col min-w-0">
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
      </div>
    </div>
  );
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
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

function PendingIndicator() {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const stage =
    secs < 3 ? "Searching the graph" : secs < 9 ? "Synthesizing answer" : "Verifying citations";
  return (
    <div className="text-sm text-muted" role="status" aria-live="polite">
      <div className="flex items-center gap-2">
        <Spinner /> {stage}…
        <span className="font-mono text-xs text-faint tabular">{secs}s</span>
      </div>
      {secs >= 6 && (
        <p className="mt-1.5 text-xs text-faint">
          Free-tier models are paced (~15s/question). A paid key makes this near-instant.
        </p>
      )}
    </div>
  );
}

function ThreadBlock({ thread }: { thread: Thread }) {
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <div className="max-w-[80%] rounded-lg rounded-tr-sm border border-border bg-surface-2 px-4 py-2 text-sm text-ink">
          {thread.question}
        </div>
      </div>

      {thread.pending && <PendingIndicator />}

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
