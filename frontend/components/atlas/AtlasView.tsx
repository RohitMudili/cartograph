"use client";

/**
 * Atlas — the architecture map (/r/[repo]/atlas). Loads the degree-ranked
 * graph slice from `GET /graph`, renders it as a community-colored force
 * layout (GraphCanvas), and pairs it with search (fuzzy fqname jump), a
 * community legend (click to spotlight a cluster), and the Inspector for the
 * selected node. `?focus=<fqname>` deep-links a node — the walkthrough uses it.
 */

import { MagnifyingGlass } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CodePanel, type CodeTarget } from "@/components/code/CodePanel";
import { GraphCanvas } from "@/components/atlas/GraphCanvas";
import { Inspector } from "@/components/atlas/Inspector";
import { TopBar } from "@/components/shell/TopBar";
import { Kbd, Spinner } from "@/components/ui";
import { ApiError, type GraphSlice, type Repo, api } from "@/lib/api";

/** Distinct, muted community colors: golden-angle hue walk, fixed s/l. */
function communityPalette(keys: string[]): Map<string, string> {
  const map = new Map<string, string>();
  keys.forEach((k, i) => {
    map.set(k, `hsl(${Math.round((i * 137.5 + 210) % 360)} 42% 62%)`);
  });
  return map;
}

export function AtlasView({ repoId }: { repoId: string }) {
  const [repo, setRepo] = useState<Repo | null>(null);
  const [graph, setGraph] = useState<GraphSlice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [focusId, setFocusId] = useState<number | null>(null);
  const [dimCommunity, setDimCommunity] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [codeTarget, setCodeTarget] = useState<CodeTarget | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    Promise.all([api.getRepo(repoId), api.getGraph(repoId)])
      .then(([r, g]) => {
        if (!active) return;
        setRepo(r);
        setGraph(g);
        // Deep link: /atlas?focus=<fqname> selects + flies to that node on load.
        const fq = new URLSearchParams(window.location.search).get("focus");
        const node = fq ? g.nodes.find((n) => n.fqname === fq) : undefined;
        if (node) {
          setSelectedId(node.id);
          setFocusId(node.id);
        }
      })
      .catch((e) => {
        if (active) setError(e instanceof ApiError ? e.detail : "Failed to load the graph.");
      });
    return () => {
      active = false;
    };
  }, [repoId]);

  // `f` focuses search (unless typing somewhere), Escape clears selection.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing =
        document.activeElement instanceof HTMLInputElement ||
        document.activeElement instanceof HTMLTextAreaElement;
      if (e.key === "f" && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const nodesById = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [n.id, n])),
    [graph],
  );
  const communityByKey = useMemo(
    () => new Map((graph?.communities ?? []).map((c) => [c.key, c])),
    [graph],
  );
  const palette = useMemo(
    () =>
      communityPalette(
        [...new Set((graph?.nodes ?? []).map((n) => n.community ?? "·"))].sort(),
      ),
    [graph],
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !graph) return [];
    return graph.nodes
      .filter((n) => n.fqname.toLowerCase().includes(q))
      .sort((a, b) => b.degree - a.degree)
      .slice(0, 8);
  }, [query, graph]);

  const selected = selectedId != null ? (nodesById.get(selectedId) ?? null) : null;
  const indexing = repo != null && repo.status !== "indexed" && repo.status !== "failed";

  function select(id: number | null) {
    setSelectedId(id);
    if (id != null) setFocusId(id);
  }

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <TopBar
        view="Atlas"
        repo={repo}
        trailing={
          graph && graph.total_nodes > graph.nodes.length ? (
            <span
              className="hidden font-mono text-xs text-faint tabular lg:inline"
              title="The map shows the most-connected symbols; search still covers them all."
            >
              mapping {graph.nodes.length} of {graph.total_nodes}
            </span>
          ) : undefined
        }
      />

      <div className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {/* search + legend overlay */}
          <div className="absolute left-4 top-4 z-10 w-64 space-y-3">
            <div className="relative">
              <MagnifyingGlass
                size={14}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint"
              />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find a symbol…"
                className="w-full rounded-md border border-border bg-surface-2 py-1.5 pl-8 pr-8 font-mono text-xs text-ink transition-colors placeholder:text-faint focus:border-border-hi"
                aria-label="Search symbols"
              />
              {!query && (
                <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
                  <Kbd>f</Kbd>
                </span>
              )}
              {matches.length > 0 && (
                <ul className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-border bg-surface-2">
                  {matches.map((n) => (
                    <li key={n.id}>
                      <button
                        onClick={() => {
                          select(n.id);
                          setQuery("");
                        }}
                        className="block w-full truncate px-3 py-1.5 text-left font-mono text-xs text-muted transition-colors hover:bg-surface-3 hover:text-ink"
                        title={n.fqname}
                      >
                        {n.fqname}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {graph && graph.communities.length > 0 && (
              <div className="max-h-56 overflow-y-auto rounded-md border border-border bg-surface-2 p-2">
                <p className="px-1 pb-1 font-mono text-[0.65rem] uppercase tracking-wide text-faint">
                  communities
                </p>
                {graph.communities.map((c) => (
                  <button
                    key={c.key}
                    onClick={() =>
                      setDimCommunity((cur) => (cur === c.key ? null : c.key))
                    }
                    className={`pressable flex w-full items-center gap-2 rounded-sm px-1.5 py-1 text-left text-xs transition-colors ${
                      dimCommunity === c.key
                        ? "bg-[var(--primary-dim)] text-ink"
                        : "text-muted hover:bg-surface-3 hover:text-ink"
                    }`}
                    title={c.summary ?? undefined}
                  >
                    <span
                      aria-hidden
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: palette.get(c.key) }}
                    />
                    <span className="truncate">{c.title ?? c.key}</span>
                    <span className="ml-auto font-mono text-[0.65rem] text-faint tabular">
                      {c.size}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* canvas / states */}
          {error && (
            <div className="flex h-full items-center justify-center px-6">
              <p className="rounded-md border border-rejected/40 bg-surface-2 px-4 py-3 text-sm text-rejected">
                {error}
              </p>
            </div>
          )}

          {!error && !graph && (
            <div className="flex h-full items-center justify-center">
              <Spinner />
            </div>
          )}

          {!error && graph && indexing && (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
              <p className="text-sm text-muted">
                This repo is still being mapped — the graph fills in as indexing runs.
              </p>
              <Link
                href={`/r/${repoId}/run`}
                className="text-sm text-primary underline-offset-4 hover:underline"
              >
                Watch it live on Mission Control →
              </Link>
            </div>
          )}

          {!error && graph && !indexing && graph.nodes.length === 0 && (
            <div className="flex h-full items-center justify-center px-6">
              <p className="text-sm text-muted">No symbols indexed for this repo yet.</p>
            </div>
          )}

          {!error && graph && !indexing && graph.nodes.length > 0 && (
            <GraphCanvas
              nodes={graph.nodes}
              edges={graph.edges}
              communityColor={palette}
              selectedId={selectedId}
              focusId={focusId}
              dimCommunity={dimCommunity}
              onSelect={select}
            />
          )}
        </div>

        {selected && (
          <Inspector
            repoId={repoId}
            node={selected}
            edges={graph?.edges ?? []}
            nodesById={nodesById}
            community={
              selected.community ? (communityByKey.get(selected.community) ?? null) : null
            }
            onNavigate={select}
            onOpenCode={() =>
              selected.path &&
              setCodeTarget({
                path: selected.path,
                startLine: selected.start_line ?? undefined,
                endLine: selected.end_line ?? undefined,
              })
            }
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      <CodePanel repoId={repoId} target={codeTarget} onClose={() => setCodeTarget(null)} />
    </div>
  );
}
