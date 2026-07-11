"use client";

/**
 * App-shell icon rail (FRONTEND.md §3) — the left 48px navigation spine shared
 * by every /r/[repo]/* view: Run (Mission Control), Atlas, Chat, Walkthrough.
 * Active view gets the amber bar + filled icon. Keyboard-first: keys 1–4
 * switch views instantly (no animation — keyboard actions are never made to
 * wait), and each item's tooltip carries its shortcut.
 */

import {
  BookOpenText,
  Broadcast,
  ChatCircleText,
  MapTrifold,
} from "@phosphor-icons/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Kbd } from "@/components/ui";

const VIEWS = [
  { slug: "run", label: "Run", key: "1", Icon: Broadcast },
  { slug: "atlas", label: "Atlas", key: "2", Icon: MapTrifold },
  { slug: "chat", label: "Chat", key: "3", Icon: ChatCircleText },
  { slug: "walkthrough", label: "Walkthrough", key: "4", Icon: BookOpenText },
] as const;

export function IconRail({ repoId }: { repoId: string }) {
  const pathname = usePathname();
  const router = useRouter();

  // 1–4 switch views (unless typing or holding a modifier). Instant on purpose.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const typing =
        document.activeElement instanceof HTMLInputElement ||
        document.activeElement instanceof HTMLTextAreaElement ||
        (document.activeElement as HTMLElement | null)?.isContentEditable;
      if (typing) return;
      const view = VIEWS.find((v) => v.key === e.key);
      if (view) router.push(`/r/${repoId}/${view.slug}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [repoId, router]);

  return (
    <nav
      aria-label="Repository views"
      className="flex w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-surface-2/60 py-3"
    >
      <Link
        href="/"
        className="pressable mb-2 flex size-9 items-center justify-center text-primary"
        title="Cartograph home"
      >
        <span aria-hidden>◆</span>
        <span className="sr-only">Home</span>
      </Link>

      {VIEWS.map(({ slug, label, key, Icon }) => {
        const href = `/r/${repoId}/${slug}`;
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={slug}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`group pressable relative flex size-9 items-center justify-center rounded-md transition-colors ${
              active ? "text-primary" : "text-muted hover:bg-surface-3 hover:text-ink"
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
            {/* Tooltip: label + shortcut. Delayed via transition-delay so a
                pass-through hover doesn't flash it; instant to disappear. */}
            <span
              aria-hidden
              className="pointer-events-none absolute left-full top-1/2 z-[70] ml-2 flex -translate-y-1/2 items-center gap-1.5 whitespace-nowrap rounded-md border border-border bg-surface-3 px-2 py-1 text-xs text-ink opacity-0 transition-opacity delay-0 duration-100 group-hover:opacity-100 group-hover:delay-300"
            >
              {label}
              <Kbd>{key}</Kbd>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
