"use client";

/**
 * The finish moment. When a run reaches its terminal state, a panel slides up
 * over the map: "Mapping finished" (with the headline counts) when the agent
 * fleet succeeded, or a graceful "Map ready" when the agent pass was skipped or
 * throttled — either way the repo is queryable, so "Chat about your repo" is
 * always offered. Hard clone/parse failures show an error with a retry.
 *
 * Motion (emil-design-eng / impeccable): a soft scrim fade + a panel that rises
 * with strong ease-out, the CTA revealing a beat later. Reduced-motion → a plain
 * crossfade. No bounce.
 */

import { ArrowRight, CheckCircle, Graph, WarningCircle } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";

import type { RunState } from "@/lib/runState";

const EASE = [0.22, 1, 0.36, 1] as const;

export function FinishPanel({
  repoId,
  state,
  onRetry,
}: {
  repoId: string;
  state: RunState;
  onRetry?: () => void;
}) {
  const router = useRouter();
  const reduce = useReducedMotion();
  const t = state.terminal;
  if (!t) return null;

  const failed = !t.ok;
  const enriched = t.enriched;

  const title = failed
    ? "Mapping failed"
    : enriched
      ? "Mapping finished"
      : "Map ready";

  const detail = failed
    ? state.error || "Something went wrong while indexing this repo."
    : enriched
      ? `${state.totals.findings} findings · ${state.totals.accepted} verified · ${t.annotations} written to the graph.`
      : `${t.nodes} symbols mapped. The agent pass was skipped${
          t.enrichmentError ? " (model unavailable)" : ""
        } — you can still ask questions, or retry enrichment.`;

  const Icon = failed ? WarningCircle : enriched ? CheckCircle : Graph;
  const accent = failed ? "text-rejected" : "text-verified";

  const container = reduce
    ? { initial: { opacity: 0 }, animate: { opacity: 1 } }
    : {
        initial: { opacity: 0, y: 24, filter: "blur(6px)" },
        animate: { opacity: 1, y: 0, filter: "blur(0px)" },
      };

  return (
    <div className="pointer-events-none absolute inset-0 z-30 flex items-end justify-center p-6 md:items-center">
      {/* scrim */}
      <motion.div
        className="absolute inset-0 bg-bg/70 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      />
      <motion.div
        {...container}
        transition={{ duration: 0.6, ease: EASE }}
        className="pointer-events-auto relative w-full max-w-md rounded-2xl border border-border bg-surface/90 p-7 text-center shadow-[0_24px_80px_-32px_oklch(0_0_0/0.9)]"
      >
        <motion.div
          initial={reduce ? false : { scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.1, ease: EASE }}
          className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-border bg-bg"
        >
          <Icon weight="fill" size={24} className={accent} />
        </motion.div>

        <h2 className="text-xl font-medium tracking-tight text-ink">{title}</h2>
        <p className="mx-auto mt-2 max-w-sm text-pretty text-sm leading-relaxed text-muted">
          {detail}
        </p>

        <motion.div
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.28, ease: EASE }}
          className="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center"
        >
          {!failed && (
            <button
              onClick={() => router.push(`/r/${repoId}/chat`)}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-on-primary transition-[filter] hover:brightness-105 active:scale-[0.98]"
            >
              Chat about your repo
              <ArrowRight weight="bold" size={16} />
            </button>
          )}
          {!enriched && onRetry && (
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm text-ink transition-colors hover:bg-surface-2 active:scale-[0.98]"
            >
              {failed ? "Try again" : "Retry enrichment"}
            </button>
          )}
        </motion.div>
      </motion.div>
    </div>
  );
}
