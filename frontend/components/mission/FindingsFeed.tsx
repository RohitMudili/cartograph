"use client";

/**
 * Findings feed — the right rail. A live stream of structured events, newest on
 * top: explorer findings (claim + target), critic verdicts (accepted = green
 * check; REJECTED stay visible, struck-through with the reason — visible
 * rejections are the trust feature, never hidden, per PRODUCT.md), and tool calls
 * (quieter). Filterable to verdicts-only. Pure render of the reduced feed.
 */

import { CheckCircle, Wrench, XCircle } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import type { FeedRow } from "@/lib/runState";

function Row({ row }: { row: FeedRow }) {
  if (row.type === "verdict") {
    const ok = row.accepted;
    return (
      <div className="border-b border-border/60 px-4 py-2.5">
        <div className="flex items-start gap-2">
          {ok ? (
            <CheckCircle weight="fill" size={15} className="mt-0.5 shrink-0 text-verified" />
          ) : (
            <XCircle weight="fill" size={15} className="mt-0.5 shrink-0 text-rejected" />
          )}
          <div className="min-w-0">
            {row.target && (
              <span
                className={`font-mono text-xs ${ok ? "text-primary" : "text-rejected line-through"}`}
              >
                {row.target}
              </span>
            )}
            <p className={`text-sm ${ok ? "text-muted" : "text-rejected/80"}`}>
              {row.revised && <span className="text-faint">[revised] </span>}
              {row.text}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (row.type === "tool_call") {
    return (
      <div className="flex items-center gap-2 border-b border-border/40 px-4 py-1.5 text-faint">
        <Wrench size={12} className="shrink-0" />
        <span className="truncate font-mono text-xs">
          <span className="text-muted">{row.label}</span> {row.text}
        </span>
      </div>
    );
  }

  // finding
  return (
    <div className="border-b border-border/60 px-4 py-2.5">
      <div className="flex items-center gap-2 font-mono text-[0.7rem] uppercase tracking-wide text-faint">
        {row.label}
        {row.target && <span className="normal-case text-accent">{row.target}</span>}
      </div>
      <p className="mt-1 text-sm text-ink">{row.text}</p>
    </div>
  );
}

export function FindingsFeed({ feed }: { feed: FeedRow[] }) {
  const [verdictsOnly, setVerdictsOnly] = useState(false);
  const reduce = useReducedMotion();
  const rows = verdictsOnly ? feed.filter((r) => r.type === "verdict") : feed;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <p className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-faint">Findings</p>
        <button
          onClick={() => setVerdictsOnly((v) => !v)}
          className={`rounded-full border px-2 py-0.5 font-mono text-[0.7rem] transition-colors ${
            verdictsOnly
              ? "border-primary/40 bg-[var(--primary-dim)] text-primary"
              : "border-border text-muted hover:text-ink"
          }`}
        >
          verdicts only
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <p className="px-4 py-3 text-sm text-faint">No findings yet.</p>
        ) : (
          rows.map((row) =>
            reduce ? (
              <div key={row.seq}>
                <Row row={row} />
              </div>
            ) : (
              <motion.div
                key={row.seq}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}
              >
                <Row row={row} />
              </motion.div>
            ),
          )
        )}
      </div>
    </div>
  );
}
