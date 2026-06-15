"use client";

/**
 * Chooses the right hero graph for the device and renders it without ever
 * blocking the initial paint:
 *
 *   - reduced-motion OR no usable WebGL OR coarse-pointer/small screen
 *       -> the lightweight 2D canvas GraphField (no Three.js loaded at all)
 *   - otherwise -> GraphField3D, lazy-loaded (ssr:false) so the ~150KB Three
 *       bundle never touches SSR or the LCP path; the headline and input render
 *       instantly and the canvas hydrates after.
 */
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { GraphField } from "./GraphField";

const GraphField3D = dynamic(
  () => import("./GraphField3D").then((m) => m.GraphField3D),
  { ssr: false, loading: () => <GraphField /> },
);

function canRender3D(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  // Skip 3D on coarse-pointer / small viewports (mobile): perf + the parallax
  // input does not apply.
  if (window.matchMedia("(pointer: coarse)").matches) return false;
  if (window.innerWidth < 768) return false;
  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") || canvas.getContext("webgl");
    return !!gl;
  } catch {
    return false;
  }
}

export function GraphFieldAuto({ paused = false }: { paused?: boolean }) {
  // Start with the 2D field (also the SSR output, so no hydration mismatch),
  // then upgrade after mount if the device qualifies. Capability detection needs
  // `window`, so it can only run client-side, in an effect. This is a one-time
  // external-capability sync, not a render-driven cascade.
  const [use3D, setUse3D] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time client capability probe
    setUse3D(canRender3D());
  }, []);

  // The 2D fallback is already near-static, so `paused` only needs to reach the
  // 3D scene (where the cursor-follow + drift live).
  return use3D ? <GraphField3D paused={paused} /> : <GraphField />;
}
