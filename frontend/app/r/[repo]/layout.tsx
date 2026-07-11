import type { ReactNode } from "react";

import { IconRail } from "@/components/shell/IconRail";

// App shell for every /r/[repo]/* view: the icon rail on the left, the view
// filling the rest. Each view keeps its own top bar (they differ per view).
// `params` is a Promise in this Next.js version — await it before use.
export default async function RepoLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ repo: string }>;
}) {
  const { repo } = await params;
  return (
    <div className="flex h-dvh bg-bg">
      <IconRail repoId={repo} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
