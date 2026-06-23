"use client";

import { ArrowRight, Graph, GitBranch } from "@phosphor-icons/react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AuthMenu } from "@/components/auth/AuthMenu";
import { Spinner, StatusChip } from "@/components/ui";
import { type RepoStatus, type RepoSummary, ApiError, api } from "@/lib/api";
import { useUser } from "@/lib/supabase/use-user";

function shortUrl(url: string): string {
  // "https://github.com/owner/repo" → "owner/repo"
  return url.replace(/^https?:\/\//, "").replace(/\.git$/, "");
}

function statusRank(status: RepoStatus): number {
  // Sort: indexed (most interesting) first, then failed, then in-progress
  switch (status) {
    case "indexed":
      return 0;
    case "failed":
      return 1;
    default:
      return 2;
  }
}

export default function ReposPage() {
  const { user, loading: authLoading } = useUser();
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRepos = useCallback(async () => {
    if (authLoading) return;
    if (!user) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const list = await api.listRepos();
      // Sort: indexed first, then failed, then in-progress
      list.sort((a, b) => statusRank(a.status) - statusRank(b.status));
      setRepos(list);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Failed to load repos.");
    } finally {
      setLoading(false);
    }
  }, [user, authLoading]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- async network call; setState runs after await
    void fetchRepos();
  }, [fetchRepos]);

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      {/* nav */}
      <nav className="flex h-16 shrink-0 items-center justify-between border-b border-border px-6 md:px-10">
        <Link href="/" className="flex items-center gap-2.5">
          <Graph weight="bold" className="text-primary" size={20} />
          <span className="font-mono text-sm uppercase tracking-[0.2em]">Cartograph</span>
        </Link>
        <div className="flex items-center gap-6">
          <AuthMenu />
        </div>
      </nav>

      {/* content */}
      <main className="flex-1 px-6 py-12 md:px-10">
        <div className="mx-auto max-w-3xl">
          {authLoading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner className="h-5 w-5 border-muted/40 border-t-muted" />
            </div>
          ) : !user ? (
            /* signed out — prompt to sign in */
            <div className="flex flex-col items-center py-20 text-center">
              <GitBranch className="text-faint" size={40} />
              <h1 className="mt-6 text-2xl font-semibold text-ink">Sign in to see your repos</h1>
              <p className="mt-3 max-w-md text-pretty text-sm text-muted">
                Repos you index will appear here once you&apos;re signed in. Sign-in
                is optional — you can still use Cartograph anonymously.
              </p>
              <div className="mt-8">
                <AuthMenu />
              </div>
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner className="h-5 w-5 border-muted/40 border-t-muted" />
            </div>
          ) : error ? (
            <div className="rounded-lg border border-rejected/40 bg-surface-2 px-5 py-4 text-sm text-rejected">
              {error}
            </div>
          ) : repos.length === 0 ? (
            /* signed in but no repos yet */
            <div className="flex flex-col items-center py-20 text-center">
              <GitBranch className="text-faint" size={40} />
              <h1 className="mt-6 text-2xl font-semibold text-ink">No repos yet</h1>
              <p className="mt-3 max-w-md text-pretty text-sm text-muted">
                Index a repo from the home page and it will show up here.
              </p>
              <Link
                href="/"
                className="mt-8 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-on-primary transition-[filter] hover:brightness-105"
              >
                <ArrowRight weight="bold" size={16} />
                Go to home
              </Link>
            </div>
          ) : (
            /* repo list */
            <>
              <div className="mb-8 flex items-center justify-between">
                <h1 className="text-2xl font-semibold text-ink">My repos</h1>
                <span className="font-mono text-xs text-faint tabular">
                  {repos.length} repo{repos.length !== 1 ? "s" : ""}
                </span>
              </div>

              <div className="space-y-3">
                {repos.map((repo) => (
                  <RepoCard key={repo.id} repo={repo} />
                ))}
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function RepoCard({ repo }: { repo: RepoSummary }) {
  const name = shortUrl(repo.url);
  const indexed = repo.status === "indexed";

  return (
    <Link
      href={`/r/${repo.id}/chat`}
      className="group block rounded-lg border border-border bg-surface/40 transition-colors hover:border-border-hi hover:bg-surface-2/60"
    >
      <div className="flex items-start justify-between gap-4 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <span className="truncate font-mono text-sm text-ink">{name}</span>
            <StatusChip status={repo.status} />
          </div>

          {/* last question */}
          {repo.last_question && (
            <p className="mt-2 truncate text-sm text-muted">
              <span className="text-faint">Last question: </span>
              {repo.last_question}
            </p>
          )}

          {/* stats row */}
          {indexed && repo.stats && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-faint tabular">
              {repo.stats.nodes != null && <span>{repo.stats.nodes} nodes</span>}
              {repo.stats.edges != null && <span>{repo.stats.edges} edges</span>}
              {repo.stats.chunks != null && <span>{repo.stats.chunks} chunks</span>}
              {repo.stats.files_parsed != null && (
                <span>{repo.stats.files_parsed} files</span>
              )}
            </div>
          )}

          {/* indexed date */}
          {repo.indexed_at && (
            <p className="mt-1.5 font-mono text-xs text-faint">
              Indexed {new Date(repo.indexed_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          )}
        </div>

        {/* arrow */}
        <span className="mt-1 shrink-0 text-faint transition-colors group-hover:text-primary">
          <ArrowRight weight="bold" size={18} />
        </span>
      </div>
    </Link>
  );
}
