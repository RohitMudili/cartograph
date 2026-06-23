"use client";

/**
 * useRunEvents — load and follow a run's agent-event stream for Mission Control.
 *
 * Replay-first: on mount it fetches the full persisted log (replay/backfill).
 * Then, depending on `mode`:
 *   - "live":   opens the WebSocket and appends new events as they arrive. If the
 *               run is already finished, the WS just confirms and closes.
 *   - "replay": ignores the live socket and instead reveals the recorded events
 *               one-by-one on a timer (the scrubber), so a completed run plays
 *               back like a recording. play/pause/speed are controlled by the
 *               returned handle.
 *
 * Either way it returns `events` (the visible prefix) which the caller folds with
 * reduceRun() — one render path for both.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { type AgentEvent, fetchRunEvents, runEventsWsUrl } from "./events";

export type StreamStatus = "loading" | "live" | "replaying" | "ended" | "error";
export type Mode = "live" | "replay";

export interface RunEventsHandle {
  events: AgentEvent[]; // visible prefix (all of them in live; up to cursor in replay)
  total: number; // total recorded events (replay mode)
  status: StreamStatus;
  mode: Mode;
  setMode: (m: Mode) => void;
  // Replay scrubber controls (no-ops in live mode):
  playing: boolean;
  setPlaying: (p: boolean) => void;
  speed: number;
  setSpeed: (s: number) => void;
  seek: (index: number) => void;
}

const SPEED_BASE_MS = 600; // ms per event at 1x

export function useRunEvents(
  repoId: string | null,
  runId: string | null,
  initialMode: Mode = "live",
): RunEventsHandle {
  const [all, setAll] = useState<AgentEvent[]>([]); // full recorded log
  const [cursor, setCursor] = useState(0); // replay reveal index (count visible)
  const [status, setStatus] = useState<StreamStatus>("loading");
  const [mode, setMode] = useState<Mode>(initialMode);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);

  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);

  // ── Backfill + (live) WebSocket ──
  useEffect(() => {
    if (!repoId || !runId) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset status when the run target changes
    setStatus("loading");

    (async () => {
      try {
        const backfill = await fetchRunEvents(repoId, runId, 0);
        if (cancelled) return;
        setAll(backfill);
        lastSeqRef.current = backfill.at(-1)?.seq ?? 0;
        setCursor(mode === "replay" ? 0 : backfill.length);

        if (mode === "replay") {
          setStatus("replaying");
          return; // replay is driven by the timer effect below
        }

        // Live: open the WS from the last seq we already have.
        const ws = new WebSocket(runEventsWsUrl(repoId, runId, lastSeqRef.current));
        wsRef.current = ws;
        ws.onopen = () => !cancelled && setStatus("live");
        ws.onmessage = (msg) => {
          if (cancelled) return;
          const ev = JSON.parse(msg.data) as AgentEvent;
          if (ev.seq <= lastSeqRef.current) return;
          lastSeqRef.current = ev.seq;
          setAll((prev) => [...prev, ev]);
          setCursor((c) => c + 1);
        };
        ws.onerror = () => !cancelled && setStatus((s) => (s === "live" ? s : "ended"));
        ws.onclose = () => !cancelled && setStatus((s) => (s === "error" ? s : "ended"));
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [repoId, runId, mode]);

  // ── Replay scrubber timer ── advances the reveal cursor; status is DERIVED
  // below (not set here) so the timer effect never calls setState synchronously.
  useEffect(() => {
    if (mode !== "replay" || !playing) return;
    if (cursor >= all.length) return;
    const id = setTimeout(() => setCursor((c) => Math.min(c + 1, all.length)), SPEED_BASE_MS / speed);
    return () => clearTimeout(id);
  }, [mode, playing, cursor, all.length, speed]);

  const seek = useCallback((index: number) => {
    setCursor(Math.max(0, index));
  }, []);

  const events = mode === "replay" ? all.slice(0, cursor) : all;

  // In replay mode, status is a pure function of progress (avoids setState-in-effect).
  const effectiveStatus: StreamStatus =
    mode === "replay" && status !== "loading" && status !== "error"
      ? cursor >= all.length
        ? "ended"
        : "replaying"
      : status;

  return {
    events,
    total: all.length,
    status: effectiveStatus,
    mode,
    setMode,
    playing,
    setPlaying,
    speed,
    setSpeed,
    seek,
  };
}
