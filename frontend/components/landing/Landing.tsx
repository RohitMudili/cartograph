"use client";

import {
  ArrowRight,
  GitBranch,
  Graph,
  Pause,
  Play,
  ShieldCheck,
  TreeStructure,
} from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import Link from "next/link";

import { AuthMenu } from "@/components/auth/AuthMenu";
import { Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useUser } from "@/lib/supabase/use-user";

import { GraphFieldAuto } from "./GraphFieldAuto";
import { MagneticButton } from "./MagneticButton";
import { useMotionPreference } from "./useMotionPreference";
import { VerifiedAnswer } from "./VerifiedAnswer";

const EASE = [0.23, 1, 0.32, 1] as const;
const DEMO_REPO = "bb357659-1d23-40e6-8065-c0d65d1763c6";

export function Landing() {
  return (
    <main className="relative overflow-x-clip bg-bg text-ink">
      <Nav />
      <Hero />
      <Proof />
      <Pipeline />
      <Economics />
      <CallToAction />
      <Footer />
    </main>
  );
}

function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.7, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Hero entrance that degrades safe: content is fully visible by default (opacity
 * stays 1 even if JS never runs), and the reveal only adds a one-time upward
 * settle after mount. No content is ever gated behind the animation completing.
 */
function HeroReveal({
  children,
  delay = 0,
  as = "div",
}: {
  children: React.ReactNode;
  delay?: number;
  as?: "p" | "h1" | "div";
}) {
  const reduce = useReducedMotion();
  const MotionTag = motion[as];

  if (reduce) return <MotionTag>{children}</MotionTag>;

  // Transform + blur only, never opacity. Motion plays initial -> animate once on
  // mount; because opacity stays 1 throughout, the resting DOM (and any frozen
  // first frame under no-JS / slow hydration) is always fully legible.
  return (
    <MotionTag
      initial={{ y: 18, filter: "blur(6px)" }}
      animate={{ y: 0, filter: "blur(0px)" }}
      transition={{ duration: 0.8, delay, ease: EASE }}
    >
      {children}
    </MotionTag>
  );
}

function Nav() {
  const { user } = useUser();
  return (
    <nav className="absolute inset-x-0 top-0 z-30 flex h-16 items-center justify-between px-6 md:px-10">
      <span className="flex items-center gap-2.5">
        <Graph weight="bold" className="text-primary" size={20} />
        <span className="font-mono text-sm uppercase tracking-[0.2em]">Cartograph</span>
      </span>
      <div className="flex items-center gap-6">
        <a
          href="https://github.com/RohitMudili/cartograph"
          target="_blank"
          rel="noreferrer"
          className="hidden items-center gap-1.5 text-sm text-muted transition-colors hover:text-ink sm:flex"
        >
          <GitBranch size={15} />
          Source
        </a>
        {user && (
          <Link
            href="/repos"
            className="flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-ink"
          >
            My repos
          </Link>
        )}
        <AuthMenu />
      </div>
    </nav>
  );
}

/* ── Hero: asymmetric split. Message + repo input on the left, the graph
   blooming off the right edge as a living illustration of the product. ── */
function Hero() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { motionEnabled, toggleMotion } = useMotionPreference();

  async function index() {
    if (!url.trim() || busy) return;
    setError(null);
    setBusy(true);
    try {
      const result = await api.indexRepo(url.trim());
      router.push(`/r/${result.repo_id}/chat`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setError("That repo is private. Sign in with GitHub for private repos (coming soon).");
      } else if (e instanceof ApiError) {
        setError(`Indexing failed: ${e.detail}`);
      } else {
        setError("Couldn't reach the backend. Is the API running on :8000?");
      }
      setBusy(false);
    }
  }

  return (
    <section className="relative min-h-[100dvh] overflow-x-clip overflow-y-hidden">
      {/* Graph bleeds off the right; anchored, not a centered backdrop. */}
      <div
        className="pointer-events-none absolute inset-y-0 right-0 z-0 w-full md:w-[62%]"
        aria-hidden
      >
        <GraphFieldAuto paused={!motionEnabled} />
        <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/40 to-transparent md:via-transparent" />
      </div>

      {/* Toggle the graph's cursor-following. The graph keeps living (nodes
          blink) either way. Persisted; honors reduced-motion. */}
      <button
        onClick={toggleMotion}
        aria-pressed={!motionEnabled}
        title={motionEnabled ? "Stop the graph from following your cursor" : "Let the graph follow your cursor"}
        className="absolute bottom-5 right-5 z-20 inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/60 px-3 py-1.5 font-mono text-[0.7rem] uppercase tracking-[0.12em] text-muted backdrop-blur-sm transition-colors hover:border-border-hi hover:text-ink active:scale-[0.97] md:bottom-7 md:right-7"
      >
        {motionEnabled ? <Pause weight="fill" size={12} /> : <Play weight="fill" size={12} />}
        {motionEnabled ? "Pause tracking" : "Resume tracking"}
      </button>

      <div className="relative z-10 mx-auto flex min-h-[100dvh] w-full max-w-[1400px] flex-col justify-center px-6 pt-24 md:px-10">
        <div className="w-full max-w-2xl">
          <HeroReveal as="p">
            <span className="flex items-center gap-2 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-muted sm:text-xs sm:tracking-[0.22em]">
              <ShieldCheck weight="fill" className="shrink-0 text-verified" size={15} />
              Verified codebase intelligence
            </span>
          </HeroReveal>

          <HeroReveal as="h1" delay={0.06}>
            <span className="mt-6 block text-balance text-[2.5rem] font-semibold leading-[1.04] tracking-tight text-ink sm:text-5xl md:text-6xl lg:text-7xl">
              Watch agents map
              <br />
              your codebase.
            </span>
          </HeroReveal>

          <HeroReveal as="p" delay={0.12}>
            <span className="mt-6 block max-w-md text-pretty text-base leading-relaxed text-muted md:text-lg">
              Paste a repo. Cartograph builds a knowledge graph and answers
              questions grounded in real code, every claim cited to the exact line
              and verified against the source.
            </span>
          </HeroReveal>

          <HeroReveal delay={0.18}>
            <div className="mt-9 max-w-lg">
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="group relative flex-1">
                <GitBranch
                  className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint transition-colors group-focus-within:text-primary"
                  size={16}
                />
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && index()}
                  disabled={busy}
                  placeholder="github.com/owner/repo"
                  aria-label="GitHub repository URL"
                  className="w-full rounded-lg border border-border bg-surface/70 py-3 pl-10 pr-4 font-mono text-sm text-ink backdrop-blur-md transition-colors placeholder:text-faint focus:border-border-hi focus:outline-none disabled:opacity-60"
                />
              </div>
              <MagneticButton
                onClick={index}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-medium text-on-primary transition-[filter] hover:brightness-105 disabled:opacity-60"
              >
                {busy ? <Spinner className="border-on-primary/40 border-t-on-primary" /> : null}
                {busy ? "Indexing" : "Map it"}
                {!busy && <ArrowRight weight="bold" size={16} />}
              </MagneticButton>
            </div>

            <div className="mt-3.5 min-h-[1.25rem]">
              {error ? (
                <p className="text-sm text-rejected">{error}</p>
              ) : (
                <p className="text-xs text-faint">
                  No setup. Try{" "}
                  <button
                    className="font-mono text-muted underline-offset-2 transition-colors hover:text-primary hover:underline"
                    onClick={() => setUrl("https://github.com/benhoyt/pybktree")}
                  >
                    benhoyt/pybktree
                  </button>{" "}
                  for an instant demo.
                </p>
              )}
            </div>
            </div>
          </HeroReveal>
        </div>
      </div>
    </section>
  );
}

/* ── Proof: the claim on the left, the live verification playing on the right.
   Asymmetric 5/7 split, no eyebrow (hero already spent the section's quota). ── */
function Proof() {
  return (
    <section className="relative border-t border-border px-6 py-24 md:px-10 md:py-32">
      <div className="mx-auto grid max-w-[1400px] items-center gap-12 lg:grid-cols-12 lg:gap-16">
        <Reveal className="lg:col-span-5">
          <h2 className="text-balance text-3xl font-semibold leading-[1.1] tracking-tight md:text-4xl">
            Most tools guess a citation.
            <br />
            <span className="text-primary">This one checks it.</span>
          </h2>
          <p className="mt-5 max-w-md text-pretty leading-relaxed text-muted">
            Every answer points at exact lines. Before you see a citation,
            Cartograph reads those lines back from the indexed source and confirms
            the claim holds. Anything it cannot back up gets flagged, never quietly
            kept.
          </p>
        </Reveal>

        <div className="lg:col-span-7">
          <VerifiedAnswer />
        </div>
      </div>
    </section>
  );
}

/* ── Pipeline: a connected three-stage flow, not three equal cards. The
   connector line draws the eye Parse -> Enrich -> Answer. ── */
function Pipeline() {
  const reduce = useReducedMotion();
  const stages = [
    {
      icon: TreeStructure,
      k: "Parse",
      t: "A structural graph, for free",
      d: "tree-sitter walks the syntax tree into nodes and edges. imports, calls, inheritance. Deterministic, no model cost.",
    },
    {
      icon: Graph,
      k: "Enrich",
      t: "Agents explore and summarize",
      d: "A fleet traverses the graph, summarizing and embedding each symbol, writing verified findings back into the structure.",
    },
    {
      icon: ShieldCheck,
      k: "Answer",
      t: "Grounded, cited, verified",
      d: "Hybrid retrieval pulls the right context. The answer cites exact lines, and every citation is checked before it reaches you.",
    },
  ];

  return (
    <section className="border-t border-border bg-surface-2/30 px-6 py-24 md:px-10 md:py-32">
      <div className="mx-auto max-w-[1400px]">
        <Reveal>
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-muted">
            How it works
          </p>
          <h2 className="mt-4 max-w-2xl text-balance text-3xl font-semibold leading-[1.1] tracking-tight md:text-4xl">
            Expensive once. Cheap to ask forever.
          </h2>
        </Reveal>

        <div className="relative mt-16 grid gap-y-12 md:grid-cols-3 md:gap-x-8">
          {/* connector line behind the stages (desktop) */}
          <div
            className="absolute left-0 right-0 top-7 hidden h-px bg-gradient-to-r from-transparent via-border-hi to-transparent md:block"
            aria-hidden
          />
          {stages.map((s, i) => {
            const Icon = s.icon;
            return (
              <motion.div
                key={s.k}
                initial={reduce ? false : { opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.4 }}
                transition={{ duration: 0.6, delay: i * 0.12, ease: EASE }}
                className="relative"
              >
                <div className="relative z-10 mb-6 flex h-14 w-14 items-center justify-center rounded-xl border border-border bg-bg">
                  <Icon weight="duotone" className="text-primary" size={24} />
                </div>
                <span className="font-mono text-xs uppercase tracking-[0.18em] text-faint">
                  {s.k}
                </span>
                <h3 className="mt-2 text-lg font-medium text-ink">{s.t}</h3>
                <p className="mt-2.5 max-w-xs text-sm leading-relaxed text-muted">{s.d}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ── Economics: data as data. Big mono numerals on hairlines, no card boxes. ── */
function Economics() {
  const stats = [
    { value: "< $1", label: "to fully index a mid-size repo, once" },
    { value: "~$0.01", label: "per follow-up question after that" },
    { value: "$0", label: "for the structural graph (no LLM)" },
  ];
  return (
    <section className="border-t border-border px-6 py-24 md:px-10 md:py-32">
      <div className="mx-auto grid max-w-[1400px] gap-12 lg:grid-cols-12 lg:items-center lg:gap-16">
        <Reveal className="lg:col-span-4">
          <h2 className="text-balance text-3xl font-semibold leading-[1.1] tracking-tight md:text-4xl">
            Index once. Ask for cents.
          </h2>
          <p className="mt-5 max-w-sm text-pretty leading-relaxed text-muted">
            The graph is built from the AST, so the model never re-reads the repo
            just to learn what is in it. The costly work happens once. Every
            question after rides the persisted graph.
          </p>
        </Reveal>

        <div className="lg:col-span-8">
          <dl className="grid divide-y divide-border border-y border-border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {stats.map((s, i) => (
              <Reveal key={s.label} delay={i * 0.1}>
                <div className="px-2 py-7 sm:px-7">
                  <dt className="font-mono text-4xl text-primary tabular md:text-5xl">
                    {s.value}
                  </dt>
                  <dd className="mt-3 max-w-[22ch] text-sm leading-snug text-muted">
                    {s.label}
                  </dd>
                </div>
              </Reveal>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

/* ── CTA: single intent (try the demo). Magnetic button, no duplicate ask. ── */
function CallToAction() {
  const router = useRouter();
  return (
    <section className="relative overflow-hidden border-t border-border px-6 py-28 md:px-10 md:py-40">
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 -z-0 h-[120%] w-[120%] -translate-x-1/2 -translate-y-1/2 opacity-[0.5]"
        aria-hidden
        style={{
          background:
            "radial-gradient(ellipse 40% 50% at 50% 50%, var(--primary-dim), transparent 70%)",
        }}
      />
      <Reveal className="relative z-10 mx-auto max-w-2xl text-center">
        <h2 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight md:text-5xl">
          See it answer a real repo.
        </h2>
        <p className="mx-auto mt-5 max-w-md text-pretty leading-relaxed text-muted">
          Open an already-indexed project and start asking. Verified answers, real
          citations, nothing to install.
        </p>
        <div className="mt-10 flex justify-center">
          <MagneticButton
            onClick={() => router.push(`/r/${DEMO_REPO}/chat`)}
            strength={0.4}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3.5 text-sm font-medium text-on-primary transition-[filter] hover:brightness-105"
          >
            Open the live demo
            <ArrowRight weight="bold" size={16} />
          </MagneticButton>
        </div>
      </Reveal>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-border px-6 py-10 md:px-10">
      <div className="mx-auto flex max-w-[1400px] flex-col items-start justify-between gap-4 text-sm text-faint sm:flex-row sm:items-center">
        <span className="flex items-center gap-2.5">
          <Graph weight="bold" className="text-primary" size={18} />
          <span className="font-mono uppercase tracking-[0.2em]">Cartograph</span>
        </span>
        <span className="font-mono text-xs">
          FastAPI · LangGraph · Gemini · Postgres + pgvector
        </span>
      </div>
    </footer>
  );
}
