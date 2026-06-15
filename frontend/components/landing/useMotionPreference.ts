"use client";

/**
 * Whether decorative hero motion (the cursor-following graph) should play.
 *
 * Defaults to ON, except: if the user has `prefers-reduced-motion` set, motion
 * starts OFF. The user's explicit toggle is persisted to localStorage and wins
 * over the media-query default on subsequent visits.
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "cartograph:hero-motion";

function readInitial(): boolean {
  if (typeof window === "undefined") return true; // SSR: assume on, settle on mount
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "on") return true;
  if (stored === "off") return false;
  // No explicit choice yet: honor the OS reduced-motion preference.
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useMotionPreference() {
  const [enabled, setEnabled] = useState(true);

  // Resolve the real initial value on mount (localStorage / media query need
  // the browser). Starting from `true` keeps SSR and first paint consistent.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client read of stored preference
    setEnabled(readInitial());
  }, []);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "on" : "off");
      } catch {
        // storage blocked (private mode, etc.) — fine, just don't persist
      }
      return next;
    });
  }, []);

  return { motionEnabled: enabled, toggleMotion: toggle };
}
