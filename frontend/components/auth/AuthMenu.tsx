"use client";

/**
 * Sign-in entry point for the nav. Signed out → a "Sign in with Google" button.
 * Signed in → the account chip with a sign-out menu. Sign-in is optional across
 * Cartograph; it only unlocks "my repos" + question history.
 *
 * Motion craft (emil-design-eng): the menu scales in from its trigger origin
 * (top-right), strong ease-out under 200ms, :active press feedback, and a
 * reduced-motion path. No animation on the high-frequency open if the user
 * prefers reduced motion.
 */
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { createClient } from "@/lib/supabase/client";
import { useUser } from "@/lib/supabase/use-user";

const configured =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL && !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

const EASE = [0.23, 1, 0.32, 1] as const;

export function AuthMenu() {
  const { user, loading } = useUser();

  // If Supabase isn't wired yet, render nothing rather than a broken button.
  if (!configured) return null;
  if (loading) return <div className="h-8 w-20" aria-hidden />;
  return user ? <AccountChip email={user.email ?? "Account"} /> : <GoogleSignIn />;
}

function GoogleSignIn() {
  const [busy, setBusy] = useState(false);

  async function signIn() {
    setBusy(true);
    const supabase = createClient();
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${next}`,
      },
    });
    // On success the browser navigates to Google; we only reach here on error.
    if (error) setBusy(false);
  }

  return (
    <button
      onClick={signIn}
      disabled={busy}
      className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm text-ink transition-colors hover:bg-surface-2 active:scale-[0.98] disabled:opacity-60"
      style={{ transitionDuration: "160ms" }}
    >
      <GoogleGlyph />
      <span>{busy ? "Redirecting…" : "Sign in"}</span>
    </button>
  );
}

function AccountChip({ email }: { email: string }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const initial = email.charAt(0).toUpperCase();

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-medium text-on-primary transition-transform active:scale-[0.96]"
        style={{ transitionDuration: "160ms" }}
        title={email}
      >
        {initial}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: -4 }}
            transition={{ duration: 0.16, ease: EASE }}
            style={{ transformOrigin: "top right" }}
            className="absolute right-0 top-10 w-56 overflow-hidden rounded-lg border border-border bg-surface shadow-[0_8px_30px_rgba(0,0,0,0.5)]"
          >
            <div className="border-b border-border px-3 py-2.5">
              <p className="text-xs text-muted">Signed in as</p>
              <p className="truncate text-sm text-ink" title={email}>
                {email}
              </p>
            </div>
            <Link
              href="/repos"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block w-full px-3 py-2.5 text-left text-sm text-ink transition-colors hover:bg-surface-2"
            >
              My repos
            </Link>
            <form action="/auth/signout" method="post">
              <button
                type="submit"
                role="menuitem"
                className="w-full px-3 py-2.5 text-left text-sm text-ink transition-colors hover:bg-surface-2"
              >
                Sign out
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function GoogleGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 18 18" aria-hidden>
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}
