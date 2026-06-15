"use client";

/**
 * The proof moment: a real query → answer → citation-verification sequence that
 * plays once when scrolled into view. Motion is motivated here. it dramatizes the
 * one claim the whole product rests on (every citation is checked against the
 * source before you see it), by showing a citation move from "checking" to
 * "verified" in front of the reader.
 *
 * No scroll listeners; the sequence is gated by Motion's `whileInView` via an
 * onViewportEnter flag, and the typing uses a single interval cleaned up on
 * unmount. Reduced motion shows the settled end-state immediately.
 */
import { CheckCircle, CircleNotch, Sparkle } from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

const ANSWER =
  "It computes the Hamming distance between two integers: it XORs them, then counts the set bits in the result. That popcount is the number of differing bit positions.";

const CITATION = "pybktree.py:22-29";

export function VerifiedAnswer() {
  const reduce = useReducedMotion();
  const [started, setStarted] = useState(false);
  const [typed, setTyped] = useState(reduce ? ANSWER.length : 0);
  // citation lifecycle: hidden -> checking -> verified
  const [phase, setPhase] = useState<"hidden" | "checking" | "verified">(
    reduce ? "verified" : "hidden",
  );
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!started || reduce) return;
    let i = 0;
    const id = setInterval(() => {
      i += 2;
      setTyped(Math.min(i, ANSWER.length));
      if (i >= ANSWER.length) {
        clearInterval(id);
        timers.current.push(setTimeout(() => setPhase("checking"), 260));
        timers.current.push(setTimeout(() => setPhase("verified"), 1500));
      }
    }, 16);
    const snapshot = timers.current;
    return () => {
      clearInterval(id);
      snapshot.forEach(clearTimeout);
    };
  }, [started, reduce]);

  return (
    <motion.div
      onViewportEnter={() => setStarted(true)}
      viewport={{ once: true, amount: 0.5 }}
      className="overflow-hidden rounded-xl border border-border bg-[oklch(0.12_0.003_91.3)] shadow-[0_24px_80px_-32px_oklch(0_0_0/0.9)]"
    >
      {/* window chrome */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[oklch(0.4_0.02_91.3)]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[oklch(0.32_0.01_91.3)]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[oklch(0.32_0.01_91.3)]" />
        <span className="ml-2 font-mono text-xs text-faint">cartograph · benhoyt/pybktree</span>
      </div>

      {/* query */}
      <div className="flex items-start gap-3 px-5 pt-5">
        <span className="select-none pt-0.5 font-mono text-sm text-primary">{">"}</span>
        <p className="font-mono text-sm text-ink">What does hamming_distance do?</p>
      </div>

      {/* answer (types in) */}
      <div className="flex items-start gap-3 px-5 pb-5 pt-3">
        <Sparkle weight="fill" className="mt-0.5 shrink-0 text-accent" size={16} />
        <p className="min-h-[3.5rem] text-sm leading-relaxed text-ink">
          {ANSWER.slice(0, typed)}
          {!reduce && typed < ANSWER.length && (
            <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-primary" />
          )}
        </p>
      </div>

      {/* citation row: resolves from checking to verified */}
      <div className="border-t border-border px-5 py-3">
        <AnimatePresence mode="wait">
          {phase === "hidden" && <div key="h" className="h-7" />}

          {phase === "checking" && (
            <motion.div
              key="c"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex items-center gap-2 font-mono text-xs text-pending"
            >
              <CircleNotch className="animate-spin" size={14} />
              checking {CITATION} against source...
            </motion.div>
          )}

          {phase === "verified" && (
            <motion.div
              key="v"
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
              className="flex flex-wrap items-center gap-2"
            >
              <span className="inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-[var(--primary-dim)] px-2.5 py-1 font-mono text-xs text-primary">
                <CheckCircle weight="fill" className="text-verified" size={14} />
                {CITATION}
              </span>
              <span className="font-mono text-xs text-faint tabular">
                1 of 1 citations verified
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
