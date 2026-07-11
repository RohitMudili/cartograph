"use client";

/**
 * Atlas inspector — the right-hand detail panel for the selected node: kind +
 * fqname, summary, community, verified-findings count, and its edges grouped by
 * kind (each row navigates). Two actions: "Ask about this" (chat with the
 * question pre-filled) and "Open code" (the shared code panel).
 */

import { ChatCircleText, FileCode, X } from "@phosphor-icons/react";
import Link from "next/link";

import type { GraphCommunity, GraphEdge, GraphNode } from "@/lib/api";

const EDGE_LABEL: Record<string, string> = {
  calls: "calls",
  imports: "imports",
  inherits: "inherits",
  implements: "implements",
  contains: "contains",
  tests: "tests",
};

export function Inspector({
  repoId,
  node,
  edges,
  nodesById,
  community,
  onNavigate,
  onOpenCode,
  onClose,
}: {
  repoId: string;
  node: GraphNode;
  edges: GraphEdge[];
  nodesById: Map<number, GraphNode>;
  community: GraphCommunity | null;
  onNavigate: (id: number) => void;
  onOpenCode: () => void;
  onClose: () => void;
}) {
  // Group this node's edges by kind, outgoing and incoming together but labeled.
  const rows: { kind: string; dir: "→" | "←"; other: GraphNode }[] = [];
  for (const e of edges) {
    if (e.src === node.id) {
      const other = nodesById.get(e.dst);
      if (other) rows.push({ kind: e.kind, dir: "→", other });
    } else if (e.dst === node.id) {
      const other = nodesById.get(e.src);
      if (other) rows.push({ kind: e.kind, dir: "←", other });
    }
  }
  const byKind = new Map<string, typeof rows>();
  for (const r of rows) {
    const list = byKind.get(r.kind) ?? [];
    list.push(r);
    byKind.set(r.kind, list);
  }

  const askHref = `/r/${repoId}/chat?q=${encodeURIComponent(
    `What does ${node.fqname} do and how is it used?`,
  )}`;

  return (
    <aside className="flex w-full flex-col overflow-hidden border-l border-border bg-surface-2/40 sm:w-[360px]">
      <header className="flex shrink-0 items-start gap-2 border-b border-border p-4">
        <div className="min-w-0">
          <span className="rounded-sm border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-accent">
            {node.kind}
          </span>
          <h2 className="mt-2 break-all font-mono text-sm text-ink">{node.fqname}</h2>
          {node.path && (
            <p className="mt-1 font-mono text-xs text-faint tabular">
              {node.path}
              {node.start_line != null && `:${node.start_line}-${node.end_line}`}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="pressable ml-auto flex size-7 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-3 hover:text-ink"
          aria-label="Close inspector"
        >
          <X size={14} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {node.summary && <p className="text-sm leading-relaxed text-muted">{node.summary}</p>}

        <dl className="mt-4 grid grid-cols-2 gap-3">
          <div>
            <dt className="font-mono text-[0.65rem] uppercase tracking-wide text-faint">
              connections
            </dt>
            <dd className="font-mono text-sm text-ink tabular">{node.degree}</dd>
          </div>
          <div>
            <dt className="font-mono text-[0.65rem] uppercase tracking-wide text-faint">
              verified findings
            </dt>
            <dd
              className={`font-mono text-sm tabular ${
                node.annotations > 0 ? "text-primary" : "text-ink"
              }`}
            >
              {node.annotations}
            </dd>
          </div>
        </dl>

        {community && (
          <div className="mt-4 rounded-md border border-border bg-surface/40 p-3">
            <p className="font-mono text-[0.65rem] uppercase tracking-wide text-faint">
              community · {community.key}
            </p>
            <p className="mt-1 text-sm text-ink">{community.title ?? "Unnamed cluster"}</p>
            {community.summary && (
              <p className="mt-1 text-xs leading-relaxed text-muted">{community.summary}</p>
            )}
            <p className="mt-1.5 font-mono text-xs text-faint tabular">
              {community.size} symbols
            </p>
          </div>
        )}

        {[...byKind.entries()].map(([kind, list]) => (
          <div key={kind} className="mt-4">
            <p className="font-mono text-[0.65rem] uppercase tracking-wide text-faint">
              {EDGE_LABEL[kind] ?? kind} · {list.length}
            </p>
            <ul className="mt-1.5 space-y-0.5">
              {list.slice(0, 12).map((r, i) => (
                <li key={i}>
                  <button
                    onClick={() => onNavigate(r.other.id)}
                    className="flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left font-mono text-xs text-muted transition-colors hover:bg-surface-3 hover:text-ink"
                    title={r.other.fqname}
                  >
                    <span className="shrink-0 text-faint" aria-hidden>
                      {r.dir}
                    </span>
                    <span className="truncate">{r.other.fqname}</span>
                  </button>
                </li>
              ))}
              {list.length > 12 && (
                <li className="px-2 py-1 font-mono text-xs text-faint">
                  +{list.length - 12} more
                </li>
              )}
            </ul>
          </div>
        ))}
      </div>

      <div className="flex shrink-0 gap-2 border-t border-border p-3">
        <Link
          href={askHref}
          className="pressable inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-medium text-on-primary transition-opacity hover:opacity-90"
        >
          <ChatCircleText size={14} />
          Ask about this
        </Link>
        <button
          onClick={onOpenCode}
          disabled={!node.path}
          className="pressable inline-flex flex-1 items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-medium text-ink transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <FileCode size={14} />
          Open code
        </button>
      </div>
    </aside>
  );
}
