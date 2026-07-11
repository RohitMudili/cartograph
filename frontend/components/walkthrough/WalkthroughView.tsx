"use client";

/**
 * Walkthrough (/r/[repo]/walkthrough) — the synthesizer's onboarding guide as
 * quiet, readable prose (FRONTEND.md §5.5): the repo summary, then an ordered
 * timeline of steps (a genuinely sequential artifact — the numbers carry
 * meaning). Steps that name a symbol deep-link into Atlas via ?focus=. A 404
 * from the API means the agent pass hasn't produced one — shown honestly with
 * pointers to Run/Chat, never as an error.
 */

import { MapTrifold } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { TopBar } from "@/components/shell/TopBar";
import { Spinner } from "@/components/ui";
import { ApiError, type Repo, type Walkthrough, api } from "@/lib/api";

export function WalkthroughView({ repoId }: { repoId: string }) {
  const reduce = useReducedMotion();
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

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <TopBar view="Walkthrough" repo={repo} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-12">
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
              <p
                className="mt-3 text-base leading-relaxed text-ink"
                style={{ textWrap: "pretty" }}
              >
                {walkthrough.summary}
              </p>

              {/* The reading path: an ordered timeline — numbers carry meaning. */}
              <ol className="relative mt-12">
                {/* connective spine through the step markers */}
                <span
                  aria-hidden
                  className="absolute bottom-3 left-3 top-3 w-px bg-border"
                />
                {walkthrough.steps.map((step, i) => (
                  <motion.li
                    key={i}
                    initial={reduce ? { opacity: 0 } : { opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.25,
                      delay: Math.min(i * 0.06, 0.4),
                      ease: [0.23, 1, 0.32, 1],
                    }}
                    className="relative pb-10 pl-12 last:pb-0"
                  >
                    <span
                      aria-hidden
                      className="absolute left-0 top-0 flex size-6 items-center justify-center rounded-full border border-primary/40 bg-bg font-mono text-xs text-primary tabular"
                    >
                      {i + 1}
                    </span>
                    <h2 className="text-sm font-medium text-ink" style={{ textWrap: "balance" }}>
                      {step.title}
                    </h2>
                    <p
                      className="mt-1.5 text-sm leading-relaxed text-muted"
                      style={{ textWrap: "pretty" }}
                    >
                      {step.detail}
                    </p>
                    {step.fqname && (
                      <Link
                        href={`/r/${repoId}/atlas?focus=${encodeURIComponent(step.fqname)}`}
                        className="pressable mt-2.5 inline-flex items-center gap-1.5 rounded-sm border border-border bg-surface-2 px-2 py-1 font-mono text-xs text-muted transition-colors hover:border-border-hi hover:bg-surface-3 hover:text-ink"
                      >
                        <MapTrifold size={13} className="text-primary" />
                        {step.fqname}
                      </Link>
                    )}
                  </motion.li>
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
