"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<string | null>(null);

  async function index() {
    setError(null);
    setBusy(true);
    setPhase("Cloning and indexing — this can take a moment…");
    try {
      const result = await api.indexRepo(url.trim());
      router.push(`/r/${result.repo_id}/chat`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setError("This repo is private. Cartograph can't access it yet.");
      } else if (e instanceof ApiError) {
        setError(`Indexing failed: ${e.detail}`);
      } else {
        setError(
          "Couldn't reach the backend at " +
            (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000") +
            ". Make sure the API server is running.",
        );
      }
      setBusy(false);
      setPhase(null);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center px-6">
      <div className="mb-2 flex items-center gap-2 text-sm text-muted">
        <span className="text-primary" aria-hidden>
          ◆
        </span>
        <span className="font-mono uppercase tracking-widest">Cartograph</span>
      </div>

      <h1 className="text-balance text-3xl font-semibold leading-tight text-ink sm:text-4xl">
        Watch agents map your codebase.
      </h1>
      <p className="mt-4 max-w-xl text-pretty leading-relaxed text-muted">
        Paste a public GitHub repo. Cartograph builds a knowledge graph and answers
        questions grounded in real code — every claim cited to the exact{" "}
        <span className="font-mono text-ink">file:line</span>, and verified against
        the source.
      </p>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && url.trim() && !busy) index();
          }}
          disabled={busy}
          placeholder="https://github.com/owner/repo"
          className="flex-1 rounded-md border border-border bg-surface px-4 py-2.5 font-mono text-sm text-ink placeholder:text-faint focus:border-border-hi disabled:opacity-60"
          aria-label="GitHub repository URL"
        />
        <Button onClick={index} disabled={!url.trim() || busy}>
          {busy && <Spinner />}
          {busy ? "Indexing…" : "Index repo"}
        </Button>
      </div>

      {phase && !error && (
        <p className="mt-4 flex items-center gap-2 text-sm text-pending" role="status">
          <Spinner className="border-pending/60 border-t-pending" />
          {phase}
        </p>
      )}
      {error && (
        <p className="mt-4 rounded-md border border-rejected/40 bg-surface-2 px-4 py-2.5 text-sm text-rejected">
          {error}
        </p>
      )}

      <p className="mt-10 text-xs text-faint">
        Try a small repo first ·{" "}
        <button
          className="font-mono text-muted underline-offset-2 hover:underline"
          onClick={() => setUrl("https://github.com/benhoyt/pybktree")}
          disabled={busy}
        >
          benhoyt/pybktree
        </button>
      </p>
    </main>
  );
}
