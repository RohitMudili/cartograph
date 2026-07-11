"use client";

/**
 * Shared top bar for the /r/[repo]/* task views — one header vocabulary so the
 * same state never looks two ways (chat previously had its own, atlas and
 * walkthrough each another). 56px: view name, repo, status, live stats; "My
 * repos" + auth on the right. Views can prepend controls via `leading`
 * (chat's sidebar toggle) and append via `trailing`.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { AuthMenu } from "@/components/auth/AuthMenu";
import { StatusChip } from "@/components/ui";
import type { Repo } from "@/lib/api";

export function TopBar({
  view,
  repo,
  leading,
  trailing,
}: {
  view: string;
  repo: Repo | null;
  leading?: ReactNode;
  trailing?: ReactNode;
}) {
  const repoName = repo?.url.replace(/^https?:\/\/github\.com\//, "") ?? "…";
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
      {leading}
      <span className="font-mono text-xs uppercase tracking-[0.18em] text-faint">{view}</span>
      <span className="text-faint/60" aria-hidden>
        /
      </span>
      <span className="truncate font-mono text-sm text-ink" title={repo?.url}>
        {repoName}
      </span>
      {repo && <StatusChip status={repo.status} />}
      {repo?.stats?.nodes != null && repo.status === "indexed" && (
        <span className="hidden font-mono text-xs text-faint tabular md:inline">
          {repo.stats.nodes} nodes · {repo.stats.edges} edges
        </span>
      )}
      <span className="ml-auto" />
      {trailing}
      <Link
        href="/repos"
        className="hidden text-sm text-muted transition-colors hover:text-ink sm:inline"
      >
        My repos
      </Link>
      <AuthMenu />
    </header>
  );
}
