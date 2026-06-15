# Cartograph — frontend

Next.js 16 · React 19 · Tailwind v4 · TypeScript. The UI for Cartograph: a
landing page, the repo-index flow, and the Chat console that shows answers with
verified `file:line` citations. Design language: "instrument panel at night"
(dark glass, amber telemetry) — see [`../DESIGN.md`](../DESIGN.md). UI plan:
[`../FRONTEND.md`](../FRONTEND.md). Code map: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

> **This is NOT the Next.js your training data assumes.** Read
> [`AGENTS.md`](AGENTS.md) and the bundled docs in `node_modules/next/dist/docs/`
> before writing Next-specific code. Notably: `params` is a `Promise` (await it),
> Tailwind v4 uses `@theme` in `globals.css` (no `tailwind.config.ts`), and
> middleware was renamed to **`proxy.ts`**.

## Getting started

```bash
cp .env.local.example .env.local    # set NEXT_PUBLIC_API_URL + Supabase URL/anon key
npm install
npm run dev                         # http://localhost:3000
```

The backend must be running on `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`)
for indexing and Q&A. `benhoyt/pybktree` is already indexed in Supabase, so pasting
it on the landing page jumps straight to chat.

## What's here

```
app/
├── page.tsx              → <Landing/>            the marketing surface
├── layout.tsx            IBM Plex fonts, metadata
├── globals.css           design tokens (@theme, OKLCH)
├── r/[repo]/chat/        the Chat console (page.tsx awaits params; ChatConsole.tsx is the UI)
└── auth/                 Google sign-in routes (callback / signout / auth-error)
proxy.ts                  Next 16 middleware — refreshes the Supabase session cookie
components/
├── ui.tsx                shared status vocabulary (StatusChip, badges, Button)
├── landing/              Landing + GraphField (2D) / GraphField3D (R3F, cursor-follow) /
│                         GraphFieldAuto, useMotionPreference (pause-tracking toggle),
│                         VerifiedAnswer (live citation terminal), MagneticButton
└── auth/AuthMenu.tsx     nav sign-in → account chip
lib/
├── api.ts                typed backend client
└── supabase/             browser/server clients, session middleware, useUser hook
```

### The hero graph

The landing hero renders a knowledge graph. `GraphFieldAuto` picks the **3D**
React Three Fiber scene (`GraphField3D`) on desktop with WebGL and motion allowed,
and falls back to the lightweight **2D** canvas (`GraphField`) on mobile,
coarse-pointer, reduced-motion, or no-WebGL. Three.js is lazy-loaded
(`next/dynamic`, `ssr: false`) so it never touches SSR or the LCP path. The graph
is illustrative; the same R3F engine is the seed for the future Mission Control
live graph.

The 3D graph **follows the cursor** (the whole graph translates toward the
pointer, with a light depth tilt), tracked at the `window` level because the
graph layer is `pointer-events-none` (it must not steal clicks from the hero
input, so the canvas never receives mouse events itself). A **"Pause tracking"**
pill in the hero corner stops the follow and snaps the graph to its default
centered state; the nodes keep their gentle blink. The choice persists via
`useMotionPreference` (localStorage) and defaults to off under
`prefers-reduced-motion`.

### Google sign-in

Optional. Uses `@supabase/ssr` (browser + server clients, cookie sessions). Sign-in
only unlocks "my repos" + history once the backend `owner_user_id` work lands.
Needs `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY`; renders nothing
if they're absent.

## Gate before pushing

```bash
npx tsc --noEmit          # types
npx eslint <changed>      # lint
npx next build            # full build
```

Verify visually too — a headless screenshot of the real render has caught layout
bugs that code review missed.
