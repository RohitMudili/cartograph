"use client";

/**
 * Walkthrough (/r/[repo]/walkthrough) — the synthesizer's onboarding guide as
 * quiet, readable prose (FRONTEND.md §5.5): the repo summary, then ordered
 * steps. Steps that name a symbol link into Atlas (deep-linked via ?focus=).
 * 404 from the API means the agent pass hasn't produced one — shown honestly
 * with pointers to Run/Chat, never as an error.
 */

import { MapTrifold } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Spinner } from "@/components/ui";
import { ApiError, type Repo, type Walkthrough, api } from "@/lib/api";

export function WalkthroughView({ repoId }: { repoId: string }) {
  const [repo, setRepo] = useState<Repo | null>(null);
  const [walkthrough, setWalkthrough] = useState<Walkthrough | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .getRepo(repoId)
      .then((r) => active && setRepo(r))
      .catch(() => {});
    api
      .getWalkthrough(repoId)
      .then((w) => active && setWalkthrough(w))
      .catch((e) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError(e instanceof ApiError ? e.detail : "Failed to load the walkthrough.");
      });
    return () => {
      active = false;
    };
  }, [repoId]);

  const repoName = repo?.url.replace(/^https?:\/\/github\.com\//, "") ?? "…";

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
        <span className="font-mono text-sm uppercase tracking-widest text-muted">
          Walkthrough
        </span>
        <span className="text-faint">/</span>
        <span className="truncate font-mono text-sm text-ink">{repoName}</span>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-10">
          {!walkthrough && !missing && !error && (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          )}

          {error && (
            <p className="rounded-md border border-rejected/40 bg-surface-2 px-4 py-3 text-sm text-rejected">
              {error}
            </p>
          )}

          {missing && (
            <div className="rounded-lg border border-border bg-surface/40 p-6">
              <p className="text-sm leading-relaxed text-muted">
                No walkthrough yet — it&apos;s written by the agent enrichment pass at the
                end of indexing, and that pass hasn&apos;t produced one for this repo
                (it&apos;s skipped when the LLM is throttled).
              </p>
              <div className="mt-4 flex gap-4 text-sm">
                <Link
                  href={`/r/${repoId}/run`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Check the index run →
                </Link>
                <Link
                  href={`/r/${repoId}/chat`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Ask questions instead →
                </Link>
              </div>
            </div>
          )}

          {walkthrough && (
            <>
              <p className="font-mono text-[0.7rem] uppercase tracking-[0.2em] text-faint">
                Getting oriented
              </p>
              <p className="mt-3 text-base leading-relaxed text-ink">
                {walkthrough.summary}
              </p>

              <ol className="mt-10 space-y-8">
                {walkthrough.steps.map((step, i) => (
                  <li key={i} className="relative pl-10">
                    <span
                      aria-hidden
                      className="absolute left-0 top-0.5 flex size-6 items-center justify-center rounded-full border border-primary/40 font-mono text-xs text-primary tabular"
                    >
                      {i + 1}
                    </span>
                    <h2 className="text-sm font-medium text-ink">{step.title}</h2>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted">{step.detail}</p>
                    {step.fqname && (
                      <Link
                        href={`/r/${repoId}/atlas?focus=${encodeURIComponent(step.fqname)}`}
                        className="mt-2 inline-flex items-center gap-1.5 font-mono text-xs text-primary underline-offset-4 hover:underline"
                      >
                        <MapTrifold size={13} />
                        {step.fqname}
                      </Link>
                    )}
                  </li>
                ))}
              </ol>

              <p className="mt-12 border-t border-border pt-4 text-xs text-faint">
                Written by the agent fleet during indexing; every claim behind it was
                verified by the critic before it reached the graph.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
