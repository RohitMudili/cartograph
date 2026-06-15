"use client";

/**
 * A button that leans toward the cursor. The pull is decorative (it makes the
 * primary action feel alive on a dark, mostly-still page) so it is driven by
 * motion values outside the React render cycle and springs back when the pointer
 * leaves. Collapses to a plain button under reduced motion.
 */
import { motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { useRef } from "react";

const SPRING = { stiffness: 220, damping: 18, mass: 0.4 };

export function MagneticButton({
  children,
  onClick,
  className = "",
  strength = 0.35,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  className?: string;
  strength?: number;
  type?: "button" | "submit";
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLButtonElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, SPRING);
  const sy = useSpring(y, SPRING);

  function onMove(e: React.PointerEvent<HTMLButtonElement>) {
    if (reduce || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    x.set((e.clientX - (r.left + r.width / 2)) * strength);
    y.set((e.clientY - (r.top + r.height / 2)) * strength);
  }
  function reset() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.button
      ref={ref}
      type={type}
      onClick={onClick}
      onPointerMove={onMove}
      onPointerLeave={reset}
      style={reduce ? undefined : { x: sx, y: sy }}
      whileTap={{ scale: 0.97 }}
      className={className}
    >
      {children}
    </motion.button>
  );
}
