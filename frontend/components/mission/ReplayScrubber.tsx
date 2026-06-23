"use client";

/**
 * Replay scrubber — the control bar for replaying a recorded run. Live vs Replay
 * toggle, play/pause, speed (1×/4×/16×), and a seek slider over the event log.
 * Only meaningful in replay mode; in live mode it shows the connection state.
 */

import { Pause, Play } from "@phosphor-icons/react";

import type { RunEventsHandle } from "@/lib/useRunEvents";

const SPEEDS = [1, 4, 16];

export function ReplayScrubber({ handle }: { handle: RunEventsHandle }) {
  const { mode, setMode, playing, setPlaying, speed, setSpeed, seek, events, total, status } =
    handle;
  const isReplay = mode === "replay";

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-2.5">
      {/* Live / Replay toggle */}
      <div className="flex overflow-hidden rounded-md border border-border">
        {(["live", "replay"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 font-mono text-xs uppercase tracking-wide transition-colors ${
              mode === m ? "bg-primary text-on-primary" : "text-muted hover:text-ink"
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {isReplay ? (
        <>
          <button
            onClick={() => setPlaying(!playing)}
            className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border text-ink transition-colors hover:bg-surface-2 active:scale-[0.96]"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause weight="fill" size={13} /> : <Play weight="fill" size={13} />}
          </button>

          <input
            type="range"
            min={0}
            max={total}
            value={events.length}
            onChange={(e) => seek(Number(e.target.value))}
            className="h-1 flex-1 cursor-pointer accent-[var(--color-primary)]"
            aria-label="Seek"
          />
          <span className="font-mono text-xs text-faint tabular">
            {events.length}/{total}
          </span>

          <div className="flex overflow-hidden rounded-md border border-border">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                className={`px-2 py-1 font-mono text-xs transition-colors ${
                  speed === s ? "bg-surface-2 text-ink" : "text-muted hover:text-ink"
                }`}
              >
                {s}×
              </button>
            ))}
          </div>
        </>
      ) : (
        <span className="font-mono text-xs text-muted">
          {status === "live" && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 animate-pulse rounded-full bg-verified" />
              live
            </span>
          )}
          {status === "loading" && "connecting…"}
          {status === "ended" && "stream ended"}
          {status === "error" && <span className="text-rejected">connection error</span>}
        </span>
      )}
    </div>
  );
}
