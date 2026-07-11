"use client";

/**
 * App-shell icon rail (FRONTEND.md §3) — the left 48px navigation spine shared
 * by every /r/[repo]/* view: Run (Mission Control), Atlas, Chat, Walkthrough.
 * Active view gets the amber bar + filled icon; tooltips carry the labels.
 */

import {
  BookOpenText,
  Broadcast,
  ChatCircleText,
  MapTrifold,
} from "@phosphor-icons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const VIEWS = [
  { slug: "run", label: "Run", Icon: Broadcast },
  { slug: "atlas", label: "Atlas", Icon: MapTrifold },
  { slug: "chat", label: "Chat", Icon: ChatCircleText },
  { slug: "walkthrough", label: "Walkthrough", Icon: BookOpenText },
] as const;

export function IconRail({ repoId }: { repoId: string }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Repository views"
      className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-surface-2/60 py-3"
    >
      <Link
        href="/"
        className="mb-2 flex size-9 items-center justify-center text-primary"
        title="Cartograph home"
      >
        <span aria-hidden>◆</span>
        <span className="sr-only">Home</span>
      </Link>

      {VIEWS.map(({ slug, label, Icon }) => {
        const href = `/r/${repoId}/${slug}`;
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={slug}
            href={href}
            title={label}
            aria-current={active ? "page" : undefined}
            className={`relative flex size-9 items-center justify-center rounded-md transition-colors ${
              active ? "text-primary" : "text-muted hover:bg-surface-2 hover:text-ink"
            }`}
          >
            {active && (
              <span
                aria-hidden
                className="absolute -left-1.5 h-5 w-0.5 rounded-full bg-primary"
              />
            )}
            <Icon size={20} weight={active ? "fill" : "regular"} />
            <span className="sr-only">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
