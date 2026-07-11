"use client";

/**
 * Code panel — a right-hand slide-over showing a file's indexed source with an
 * amber-highlighted line range. Opened from a Chat citation chip or Atlas's
 * "Open code"; the source comes from `GET /api/repos/{id}/file` (reconstructed
 * from the indexed chunks — exactly what the citation verifier checked, so what
 * you read here is what was verified).
 */

import { Check, Copy, X } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { Spinner } from "@/components/ui";
import { ApiError, type FileContent, api } from "@/lib/api";

export interface CodeTarget {
  path: string;
  /** 1-based inclusive highlight range; omit to show the file unhighlighted. */
  startLine?: number;
  endLine?: number;
}

export function CodePanel({
  repoId,
  target,
  onClose,
}: {
  repoId: string;
  target: CodeTarget | null;
  onClose: () => void;
}) {
  const reduce = useReducedMotion();
  // Loaded result keyed to the target it belongs to — a mismatch means loading.
  // (State is only ever set from async callbacks, never synchronously in effects.)
  const [loaded, setLoaded] = useState<{
    target: CodeTarget;
    file: FileContent | null;
    error: string | null;
  } | null>(null);
  const highlightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target) return;
    let active = true;
    api
      .getFile(repoId, target.path)
      .then((f) => {
        if (active) setLoaded({ target, file: f, error: null });
      })
      .catch((e) => {
        if (active)
          setLoaded({
            target,
            file: null,
            error: e instanceof ApiError ? e.detail : "Failed to load the file.",
          });
      });
    return () => {
      active = false;
    };
  }, [repoId, target]);

  const current = loaded && loaded.target === target ? loaded : null;
  const file = current?.file ?? null;
  const error = current?.error ?? null;

  // Scroll the highlighted range into view once the file renders.
  useEffect(() => {
    if (file?.found && highlightRef.current) {
      highlightRef.current.scrollIntoView({ block: "center" });
    }
  }, [file]);

  // Escape closes.
  useEffect(() => {
    if (!target) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  return (
    <AnimatePresence>
      {target && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-40 bg-black/50"
            onClick={onClose}
            aria-hidden
          />
          <motion.aside
            key="panel"
            initial={reduce ? { opacity: 0 } : { x: "100%" }}
            animate={reduce ? { opacity: 1 } : { x: 0 }}
            exit={reduce ? { opacity: 0 } : { x: "100%" }}
            transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-border bg-surface"
            role="dialog"
            aria-label={`Source of ${target.path}`}
          >
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
              <span className="truncate font-mono text-sm text-ink">{target.path}</span>
              {target.startLine != null && (
                <span className="shrink-0 rounded-sm bg-[var(--primary-dim)] px-1.5 py-0.5 font-mono text-xs text-primary tabular">
                  {target.startLine}
                  {target.endLine != null && target.endLine !== target.startLine
                    ? `–${target.endLine}`
                    : ""}
                </span>
              )}
              <span className="ml-auto" />
              <CopyPathButton
                text={
                  target.startLine != null
                    ? `${target.path}:${target.startLine}`
                    : target.path
                }
              />
              <button
                onClick={onClose}
                className="pressable flex size-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-3 hover:text-ink"
                aria-label="Close code panel"
              >
                <X size={16} />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-auto">
              {!file && !error && (
                <div className="flex h-full items-center justify-center">
                  <Spinner />
                </div>
              )}

              {error && <p className="px-4 py-6 text-sm text-rejected">{error}</p>}

              {file && !file.found && (
                <p className="px-4 py-6 text-sm text-muted">
                  This file isn&apos;t in the index — it may not contain any parsed symbols.
                </p>
              )}

              {file?.found && (
                <FileSource
                  file={file}
                  startLine={target.startLine}
                  endLine={target.endLine}
                  highlightRef={highlightRef}
                />
              )}
            </div>

            {file?.truncated && (
              <p className="shrink-0 border-t border-border px-4 py-2 text-xs text-faint">
                Long file — showing the indexed portion.
              </p>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function CopyPathButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="pressable flex size-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-3 hover:text-ink"
      aria-label={copied ? "Copied" : `Copy ${text}`}
      title={copied ? "Copied" : "Copy file:line"}
    >
      {copied ? <Check size={15} className="text-verified" /> : <Copy size={15} />}
    </button>
  );
}

function FileSource({
  file,
  startLine,
  endLine,
  highlightRef,
}: {
  file: FileContent;
  startLine?: number;
  endLine?: number;
  highlightRef: React.RefObject<HTMLDivElement | null>;
}) {
  const firstLine = file.start_line ?? 1;
  const lines = file.text.split("\n");
  const hiStart = startLine ?? -1;
  const hiEnd = endLine ?? hiStart;

  return (
    <pre className="px-0 py-3 font-mono text-xs leading-relaxed">
      {lines.map((line, i) => {
        const n = firstLine + i;
        const hi = n >= hiStart && n <= hiEnd;
        return (
          <div
            key={n}
            ref={hi && n === hiStart ? highlightRef : undefined}
            className={`flex ${hi ? "bg-[var(--primary-dim)]" : ""}`}
          >
            <span
              className={`w-12 shrink-0 select-none pr-3 text-right tabular ${
                hi ? "text-primary" : "text-faint"
              }`}
              aria-hidden
            >
              {n}
            </span>
            <code className={`whitespace-pre ${hi ? "text-ink" : "text-muted"}`}>
              {line || " "}
            </code>
          </div>
        );
      })}
    </pre>
  );
}
