"use client";

/**
 * /r/[repo] — routes to the right view for the repo's state (FRONTEND.md §2):
 * still indexing → Mission Control (/run); indexed → Atlas. Client-side because
 * the decision needs the repo's live status.
 */

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function RepoIndexPage() {
  const { repo } = useParams<{ repo: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!repo) return;
    let active = true;
    api
      .getRepo(repo)
      .then((r) => {
        if (!active) return;
        router.replace(
          r.status === "indexed" || r.status === "failed"
            ? `/r/${repo}/atlas`
            : `/r/${repo}/run`,
        );
      })
      .catch(() => {
        if (active) router.replace(`/r/${repo}/chat`);
      });
    return () => {
      active = false;
    };
  }, [repo, router]);

  return (
    <div className="flex h-dvh items-center justify-center bg-bg">
      <Spinner />
    </div>
  );
}
