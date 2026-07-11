/**
 * Shared UI vocabulary (DESIGN.md §Components). One status language across the
 * app — the same state never looks two ways.
 */
import type { ReactNode } from "react";

import type { RepoStatus } from "@/lib/api";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-border border-t-primary ${className}`}
      aria-hidden
    />
  );
}

/** Verified / unverified citation marker — icon + label, never colour alone. */
export function VerifyBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="inline-flex items-center gap-1 text-verified" title="Verified against source">
      <span aria-hidden>✓</span>
      <span className="sr-only">verified</span>
    </span>
  ) : (
    <span
      className="inline-flex items-center gap-1 text-rejected"
      title="Could not verify this citation against the source"
    >
      <span aria-hidden>✕</span>
      <span className="sr-only">unverified</span>
    </span>
  );
}

export function RouteBadge({ route }: { route: string }) {
  return (
    <span className="rounded-sm border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-xs uppercase tracking-wide text-accent">
      {route}
    </span>
  );
}

const STATUS_LABEL: Record<RepoStatus, string> = {
  pending: "Queued",
  cloning: "Cloning",
  parsing: "Parsing",
  summarizing: "Summarizing",
  indexed: "Indexed",
  failed: "Failed",
};

export function StatusChip({ status }: { status: RepoStatus }) {
  const active = status !== "indexed" && status !== "failed";
  const tone =
    status === "indexed"
      ? "text-verified border-verified/40"
      : status === "failed"
        ? "text-rejected border-rejected/40"
        : "text-pending border-pending/40";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border bg-surface-2 px-2 py-0.5 text-xs ${tone}`}
    >
      {active && <Spinner className="border-pending/60 border-t-pending" />}
      {status === "indexed" && <span aria-hidden>●</span>}
      {status === "failed" && <span aria-hidden>✕</span>}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
  children: ReactNode;
}) {
  const base =
    "pressable inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "primary"
      ? "bg-primary text-on-primary hover:opacity-90"
      : "border border-border text-ink hover:bg-surface-3";
  return (
    <button className={`${base} ${styles}`} {...props}>
      {children}
    </button>
  );
}

/** Keyboard-shortcut hint — mono, quiet, never color-only. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-4 min-w-4 items-center justify-center rounded-[3px] border border-border bg-surface-2 px-1 font-mono text-[0.6rem] leading-none text-faint">
      {children}
    </kbd>
  );
}
