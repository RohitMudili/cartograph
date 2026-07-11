# Cartograph — Frontend Plan

Companion to `PLAN.md` (§5 superseded by this document). Strategy lives in
`PRODUCT.md`; visual tokens live in `DESIGN.md`. This file is the build plan:
information architecture, interaction model, per-view specs, state layer,
quality bars, and the build order.

**Design concept — "instrument panel at night."** Dark glass, amber telemetry,
mono numerals. Three layered interaction registers (deliberately, per design
review): **Raycast-style command palette** for intent ("ask, jump, index"),
**Linear-style precision surfaces** for the work (Atlas, Chat — dense, calm,
keyboard-first), and **Vercel-style observability** for the live layer (Mission
Control + an always-available telemetry drawer). The brand bet: the most
beautiful thing on screen is *real agent activity rendered faithfully*.

---

## 1. Scope

**In:** Landing page (brand surface), app shell, Mission Control (live +
replay), Atlas, Chat, Walkthrough overlay, command palette, telemetry drawer,
all loading/empty/error states, reduced-motion support, the demo recording.

**Out (v2):** light theme, mobile-first layouts (graceful read-only fallback
only), auth/multi-user, collaborative cursors, VS Code webview.

---

## 2. Information Architecture & Routes

```
/                      Landing (brand register; no app shell)            ✅ BUILT
                         the repo-paste/index flow lives in the hero
                         (the planned standalone /new page was folded in)
/auth/callback         Google OAuth PKCE exchange                        ✅ BUILT
/auth/signout          POST-only sign-out                               ✅ BUILT
/auth/auth-error       Sign-in failure surface                          ✅ BUILT
/r/[repo]              Redirects to /run while indexing, else /atlas     ✅ BUILT
/r/[repo]/run          Mission Control — live during runs, Replay after  ✅ BUILT
/r/[repo]/atlas        Architecture graph + inspector                    ✅ BUILT (canvas force layout, not Sigma — see §5.3 note)
/repos                "My repos" page (signed-out/empty/list states)      ✅ BUILT
/r/[repo]/chat         Research console (threads, citations, session sidebar) ✅ BUILT (+ code panel on chip click)
/r/[repo]/walkthrough  Generated onboarding doc                          ✅ BUILT (steps deep-link into Atlas via ?focus=)
/r/[repo]/settings     Re-index, budgets, danger zone                    ❌
```

- **URL is state** in Atlas and Chat: focused node, zoom level, active filters,
  selected thread are all query params → every interesting view is shareable
  and the demo video can deep-link.
- Global **⌘K command palette** from every route: "Ask: …" (→ chat with the
  query pre-filled), "Go to node …" (fuzzy symbol search), "Switch repo",
  "Re-index", "Toggle telemetry drawer", "Copy share link", "Replay last run".
- Keyboard map: `⌘K` palette · `[` drawer · `1/2/3/4` view switch · `/` focus
  chat input · `f` focus-node search in Atlas · `esc` universal dismiss.

## 3. App Shell

- **Top bar (56px):** wordmark glyph → repo switcher (palette-backed) →
  `CommitBadge` (`fastapi @ a1b2c3 · 2 behind` — click = re-index affordance) →
  run status chip → right side: live `CostTag` (session spend, mono, amber),
  `⌘K` hint, settings.
- **Icon rail (48px, left):** Run / Atlas / Chat / Walkthrough. Active = amber
  bar + filled icon. Tooltips with shortcut hints.
- **Telemetry drawer (right, 360px, `[` to toggle):** the Vercel-style
  observability layer, available in *every* view. Tabs: **Activity** (live
  agent events, compact), **Run stats** (tokens, cost, timings per agent),
  **Question log** (route + cost + latency per question). During an index run
  it mirrors Mission Control in miniature; during chat escalations it
  auto-opens to show the spawned explorer. This is "Show Thought Process" as a
  persistent, togglable surface.

## 4. State & Data Layer

| Concern | Choice | Notes |
|---|---|---|
| Server state | TanStack Query | repos, graph slices, questions, evals; SSR-friendly; retry/backoff for free |
| Live events | Native WebSocket → **Zustand event store** | one store per run: append-only `events[]` keyed by `seq`, derived maps (per-agent state, totals). Reconnect sends `last_seq`; gaps re-fetched from `GET /runs/{id}/events?after_seq=` — UI can never miss events. |
| Answer streaming | SSE (`fetch` + ReadableStream) | token append into the active thread; citations parsed from the final frame |
| Atlas view state | URL params + small Zustand slice | camera, focus node, filters; back/forward works |
| Derived data | selectors, memoized | e.g. `agentRoster(events)`, `territoryMap(events)`, `costSeries(events)` |

**Replay is the same code path as live:** Mission Control consumes the event
store; live mode feeds it from the WebSocket, replay mode feeds it from the
persisted event log through a timeline scrubber (play/pause/speed). One
renderer, two sources — this gives the demo a rewind button and makes the view
testable with fixture event logs (no backend needed for UI development).

Type safety end-to-end: OpenAPI schema → generated TS client; the WS event
envelope is a discriminated union mirrored from `agents/schemas.py`.

## 5. View Specs

### 5.1 Landing page `/` (brand register) — ✅ BUILT

> **Status:** built and shipped (`components/landing/`). The spec below is the
> original plan; the **"As built"** note records what actually shipped, which
> diverged where the live-replay/eval-data dependencies don't exist yet.

One scroll, typography-led. No section eyebrows, no numbered-section scaffolding,
no card grids, no gradient text, zero em-dashes — the decoration budget is spent on
the hero graph and one live moment.

Original five-beat plan:

1. **Hero:** display headline ("Watch agents map your codebase."), one
   sub-sentence, single amber CTA. Behind/below: a **real replay** of a recorded
   fastapi index run rendered by the actual Mission Control components.
2. **The economics:** the cost chart from real eval data, house style.
3. **The verification loop:** a strip showing one claim's lifecycle.
4. **The atlas:** one full-bleed Atlas screenshot with callout captions.
5. **Footer:** GitHub link, eval scoreboard, tech credit, author.

**As built** (`Landing.tsx`, composed of `Nav / Hero / Proof / Pipeline /
Economics / CallToAction / Footer`):

1. **Hero** — asymmetric split: headline + sub-sentence + the **repo-paste input**
   (the index flow lives here, replacing a separate `/new` page) + a magnetic
   "Map it" CTA on the left; a **living knowledge graph** bleeding off the right
   edge. The graph is the restrained **3D R3F** `GraphField3D` on desktop+WebGL,
   the 2D canvas `GraphField` everywhere else (`GraphFieldAuto` gates it; Three.js
   is lazy-loaded `ssr:false`). It is *illustrative*, not a live replay — the real
   replay-on-Mission-Control idea waits on the event stream + fleet.
   - **Cursor interaction:** the 3D graph follows the cursor (the whole graph
     translates toward the pointer, plus a light depth tilt), tracked at the
     `window` level (the canvas is `pointer-events-none`). Nodes always blink
     (a gentle bob + pulse).
   - **"Pause tracking" pill** (hero bottom-right): stops the cursor-follow and
     snaps the graph to its default centered state; nodes keep blinking. The
     choice persists (`useMotionPreference` → localStorage) and defaults to off
     when `prefers-reduced-motion` is set.
2. **Proof** — replaces the eval cost chart (no eval data yet). A claim on the left
   and `VerifiedAnswer` on the right: a live terminal where the answer types in and
   a citation resolves `checking → verified`. This carries beat 3's "verification
   loop" thesis as motivated motion.
3. **Pipeline** — a connected Parse → Enrich → Answer flow (Phosphor icons on a
   drawn connector), not three equal cards.
4. **Economics** — the cost story as large amber mono numerals on hairlines (placeholder
   figures `< $1 / ~$0.01 / $0`, to be replaced by real eval data when it exists).
5. **CTA + Footer** — single CTA intent ("Open the live demo" → the demo repo's
   chat); footer with the tech-stack strip. Eval scoreboard + live star count are
   deferred (no eval data; no live GitHub fetch yet).

**Deferred to when their data exists:** real index-run replay in the hero, the
eval cost chart, the Atlas screenshot beat, the eval scoreboard table. The hero
graph engine (`GraphField3D`) is deliberately the **seed of the Mission Control
live graph** — same R3F renderer, camera, instanced node/edge primitives.

**Nav also hosts Google sign-in** (`AuthMenu`) and a visible **"My repos" link** when
the user is signed in. The `Landing.tsx` Nav component shows `useUser()` state and
conditionally renders the link next to "Source". See `ARCHITECTURE.md` Flow 4 and
`PLAN.md §9B`.

### 5.2 Mission Control `/r/[repo]/run` — ✅ BUILT

> **Status:** built (`components/mission/` + `lib/{events,runState,useRunEvents}.ts`).
> The spec below is the original plan; **"As built"** notes where it diverged. The
> data path is replay-first: resolve `repo.latest_run_id` → replay the durable
> `agent_events` log (`?after_seq=`) → follow the live WS. A pure `reduceRun`
> reducer turns events into the view model, so live and replayed runs render
> identically. Verified end-to-end via headless capture.
>
> **As built:** Pasting a repo on the landing page routes straight here (the index
> runs in the background; an already-indexed repo goes to chat instead). The view
> opens with a **PhaseIntro** — a cloning → parsing → summarizing checklist — before
> the agents spawn. Once they do: `[roster | territory graph (R3F) | findings feed]`
> over a **ReplayScrubber** (LIVE/REPLAY · play/pause · 1×/4×/16× · seek) and a
> **RunFooter** (phase pipeline + findings/verified/rejected/tokens/cost). Roster
> cards show role glyph + state dot (pulsing amber=working, green ✓=done, red=failed)
> + activity + tool/finding counts. Feed shows findings and critic verdicts with
> **rejections struck-through and kept visible**. The territory graph is the hero's
> R3F engine: nodes are the symbols the fleet touched, verified ones lock to amber.
> On the run's terminal event a **FinishPanel** slides up: "Mapping finished" when
> the fleet ran, or a graceful "Map ready (agent pass skipped)" + Retry when the
> fleet was throttled (e.g. Gemini quota) — always with a **"Chat about your repo"**
> CTA, so the page never hangs. Deferred vs the plan below: the treemap/icicle
> territory layout (we use the 3D node field instead), the per-agent token
> sparkline, and Cancel.

The spectacle view; Committed color strategy (amber earns ~30% of the surface).
Grid: `[roster 320px | territory map 1fr | findings 380px]` over a 64px footer.

- **Agent roster (left):** planner → explorers → synthesizer → critic as
  vertically stacked `AgentCard`s. Anatomy: agent glyph + ramp color, name,
  state dot (pulsing amber = working, solid = idle, green ✓ = done, red ✕ =
  failed/cancelled), one-line current activity (`reading src/auth/jwt.py`),
  live token meter (mono). Card border glows faintly (`--glow-live`) only
  while that agent is mid-tool-call.
- **Territory map (center):** the repo as a zoomable treemap/icicle of files
  (cheap to render at any repo size, reads instantly — the force graph stays in
  Atlas). Regions tint with their explorer's ramp color as territory is
  claimed; cells flash amber for the active file read; verified-annotation
  count renders as small density dots. Hover = file path tooltip; click =
  pre-fills "ask about this file".
- **Findings feed (right):** virtualized stream of structured events, newest
  on top. Three row types with distinct anatomy: **finding** (agent badge +
  claim text + target `path:line`), **verdict** (critic row — verified rows get
  the green check; **rejected rows stay in the feed**, struck through with the
  critic's reason — visible rejections are the trust feature, never hide
  them), **system** (phase transitions: "Leiden clustering: 14 communities").
  Filter chips: per-agent, verdicts-only.
- **Footer (run telemetry):** elapsed · events/s sparkline · token total ·
  **cost ticker** (mono, amber, tweening) · phase progress (static pass →
  exploration → synthesis → communities) · Cancel (with confirm).
- **Replay mode:** same layout + timeline scrubber on the footer (play/pause,
  1×/4×/16×, phase markers). Entered automatically for completed runs; "Replay
  this run" is also a palette action. Empty state for a repo with no runs
  teaches the `/new` flow.

### 5.3 Atlas `/r/[repo]/atlas`

The map; Restrained color (the graph's own data is the color). Layout:
`[canvas 1fr | inspector 360px]`, inspector collapsible.

- **Canvas:** Sigma.js (WebGL). **Semantic zoom:** far = community bubbles
  (sized by node count, labeled, summary on hover); mid = files within the
  focused community; near = symbols. Crossfade between levels at fixed camera
  thresholds, 400ms. Edges by kind (line styles, not just colors): imports
  solid, calls directed-dashed, inherits dotted; `confidence: low` edges render
  at 40% opacity and say so in the tooltip.
- **Inspector (right):** on node select — kind chip + fqname (mono), LLM
  summary, **annotations list with verification chips and source attribution**
  ("explorer_3, verified by critic, run #12"), metrics row (LOC, fan-in/out,
  churn — mono), edges grouped by kind (each row navigates), and two actions:
  **"Ask about this"** (→ chat, context pre-filled) and **"Open code"** (code
  panel slides over the inspector).
- **Top-left overlay:** search (`f` — fuzzy fqname jump with camera flight),
  filter chips (edge kinds, node kinds, min-confidence), "fit view".
- **Walkthrough overlay:** ordered amber path drawn through the graph; step
  card (bottom center) with prose + prev/next (`←/→`); non-walkthrough nodes
  dim to 25%. Exiting restores previous camera.
- **Performance contract:** never mount >1,500 DOM-free WebGL nodes per level;
  community aggregation handles the rest. Layout positions computed server-side
  (or in a worker) and cached per commit — the camera animates, the layout
  doesn't reflow on every visit.
- **Empty/edge states:** repo still indexing → live "regions appearing" mini
  view + link to Run; >5k files → banner naming the partial-index policy.

### 5.4 Chat `/r/[repo]/chat`

A research console, not a chatbot. Layout: `[threads 280px | conversation 1fr |
code panel 480px (on demand)]`.

- **Threads rail:** question history with `RouteBadge` (local/global/escalated)
  + `CostTag` per thread; "New question" = `/`.
- **Conversation:** user question (right-aligned, quiet) → answer block:
  streamed markdown (70ch measure), **citation chips** inline (`auth/jwt.py:42`
  — mono, amber underline). Hover = code peek tooltip; click = code panel opens
  scrolled to the range with the verified quote highlighted amber. Citations
  that failed verification render as `--rejected` with strikethrough and an
  "unverified claim" tooltip — the honesty rule from PRODUCT.md.
- **Transparency strip** (footer of every answer, the signature element): route
  badge · cost (mono) · latency · "used 14 nodes" → hover/click highlights the
  consulted subgraph as a mini-map; "open in Atlas" deep-links it.
- **Escalation theater:** when the router escalates, an inline compact agent
  card appears in the thread (same component as Mission Control roster) showing
  the live explorer; the telemetry drawer auto-opens. On completion the answer
  streams and a quiet amber line notes: **"✦ graph updated — this answer is
  cheaper next time."** (The product thesis, rendered.)
- **States:** answer error → retry affordance with the failure named; "not in
  this repo" refusals styled as a distinct calm state (not an error); input
  disabled with reason while repo is mid-index.

### 5.5 Walkthrough `/r/[repo]/walkthrough`

The generated onboarding doc as readable prose (70ch, generous rhythm): ordered
steps, each with file links (→ code panel) and an "open in Atlas" map thumbnail
per step. "Start guided tour" switches to the Atlas overlay mode. This view is
deliberately quiet — it's the one surface that should print well.

### 5.6 `/new` flow

Single centered panel: URL input (validates host allowlist inline), size/budget
notice ("repos up to ~5k files; indexing costs roughly $0.50–1.00"), submit →
redirects to Mission Control which starts populating within seconds (the static
pass emits events immediately — no dead air; skeleton roster until the planner
reports). Failure states named specifically: clone failed / too large / rate
limited.

## 6. Component Architecture

```
components/                                                         (planned vs built)
├── ui.tsx         # ✅ shared vocabulary (StatusChip, VerifyBadge, RouteBadge, Button)
│                  #    (kept as one file for now, not a ui/ dir of shadcn primitives)
├── landing/       # ✅ BUILT — Landing (composes the page), GraphField (2D),
│   GraphField3D (R3F, cursor-follow), GraphFieldAuto (gate+lazy),
│   useMotionPreference (pause-tracking toggle state), VerifiedAnswer (live cite
│   terminal), MagneticButton. NOTE: the originally-planned ReplayEmbed/CostChart/
│   VerificationStrip/EvalTable were replaced by the graph hero + VerifiedAnswer
│   (their data — real replays, eval results — does not exist yet).
├── auth/          # ✅ AuthMenu (nav sign-in → account chip + sign-out)
├── mission/       # ✅ BUILT — Mission Control: MissionControl, AgentRoster,
│   FindingsFeed, RunFooter, ReplayScrubber, TerritoryGraph (R3F). Driven by the
│   pure reducer lib/runState.ts + the lib/useRunEvents.ts hook (replay + live WS).
│   (Supersedes the planned telemetry/ dir for the live-run view.)
├── atlas/         # ✅ BUILT — AtlasView (search, community legend/spotlight, states),
│   GraphCanvas (hand-rolled 2D canvas force layout: seeded FR, progressive rAF
│   settle, pan/zoom/hover/click, camera flights), Inspector (summary, community
│   card, grouped edges that navigate, "Ask about this" → chat ?q=, "Open code").
│   NOTE: chose plain canvas over Sigma.js — the API caps the slice at ~400
│   degree-ranked nodes, and it keeps the bundle small. Deferred: semantic-zoom
│   community bubbles, edge line-styles per kind, walkthrough path overlay.
├── code/          # ✅ BUILT — CodePanel: slide-over source viewer over GET /file,
│   cited range highlighted amber + scrolled into view; shared by Chat + Atlas.
├── walkthrough/   # ✅ BUILT — WalkthroughView: quiet prose steps, honest empty
│   state, per-step deep links into Atlas (?focus=<fqname>).
├── chat/          # ⚠️ Chat is built but as one ChatConsole.tsx (under app/r/[repo]/chat/),
│   not yet split into Thread/AnswerBlock/CitationChip/TransparencyStrip/…
│   Citation chips now open the shared CodePanel; ?q= pre-fills the composer.
└── shell/         # ⚠️ IconRail ✅ BUILT (via app/r/[repo]/layout.tsx).
│   TopBar, TelemetryDrawer, CommandPalette, RepoSwitcher remain ❌.
```

> The Atlas graph will use Sigma.js (WebGL, 2D semantic zoom) per §5.3. The
> **landing's R3F engine** (`GraphField3D`) is separately the seed for the Mission
> Control *live* graph — different tool, same "graph in motion" job.

Rules: telemetry components are **pure functions of the event store** (renders
identically live or replayed, testable on fixtures). `StatusChip`, `AgentBadge`,
`RouteBadge`, `CostTag` are the shared vocabulary — no view defines its own
status visuals (PRODUCT.md principle 5). Storybook (or Ladle) hosts every
component in all states from fixture data; the design pass happens there before
views compose them.

## 7. Motion Plan

Per DESIGN.md timings. Choreography worth specifying:

- **Feed entrances:** rise+fade 180ms, 40ms stagger, capped — under event
  bursts, rows batch (one frame, no animation) so the feed never lags truth.
- **Territory claims:** 250ms fill sweep; active-read flash 150ms.
- **Graph:** camera flights 400ms ease-out-quint; level crossfades; walkthrough
  path draws in once (600ms, `stroke-dashoffset`) when entering tour mode.
- **Counters:** numeric tween, 300ms, mono so width is stable.
- **Palette:** scale 0.98→1 + fade, 150ms.
- **Live pulses:** agent state dot only. Nothing else loops, ever.
- **Reduced motion:** dots solid, entrances 120ms fade, camera jumps+crossfade,
  path appears instantly. Verified at review time with the OS setting on.

## 8. Hardening (states that must exist before "done")

- **WS lifecycle UX:** connecting / live / reconnecting (amber bar: "reconnecting
  — events will catch up") / caught-up toast. Never silently stale.
- **Run failure:** agent crash or budget abort renders as a system feed row +
  footer state, with partial-index explanation and "results still usable" note.
- **Empty states (teaching):** no repos → `/new` pitch; no questions → three
  example questions as clickable chips; atlas before enrichment → "structural
  map ready, summaries arriving" with live fill.
- **Error boundaries** per view (a graph crash must not take down chat) with a
  "copy diagnostics" action (run id, last seq).
- **Long content:** 10k-event runs (virtualization + "jump to live"), 400-line
  citation ranges (code panel caps + "open full file"), repo names that
  truncate (middle-ellipsis, title attr).
- **Responsive:** per DESIGN.md — ≥1280 full, tablet drawer-overlay + bottom
  sheets, <768 read-only chat/walkthrough/landing with honest messaging.

## 9. Performance Budgets

| Budget | Target | Enforcement |
|---|---|---|
| Landing LCP | < 1.5s (replay embed lazy, poster first) | Lighthouse CI |
| App route JS | < 250KB gz per view (Sigma + virtuoso code-split per route) | bundle check in CI |
| Event ingest | 200 events/s without dropped frames | fixture stress story |
| Graph interaction | 60fps pan/zoom at 1,500 rendered nodes | manual perf story |
| Answer stream | first token rendered < 100ms after SSE frame | dev assert |
| Font loading | Plex Sans/Mono subset, `font-display: swap`, preloaded | build config |

## 10. Accessibility Checklist (ship gate)

- [ ] Contrast audit on final tokens: `--ink`/`--muted` vs all three surfaces ≥ 4.5:1; chip text on tinted fills ≥ 4.5:1.
- [ ] Full keyboard pass: palette-only navigation of the entire app; visible `--glow-focus` everywhere; focus trap + restore in palette/dialogs/drawer.
- [ ] Graph fallback: every Atlas operation achievable via search + inspector list (canvas is enhancement, not requirement); canvas has an offscreen text summary.
- [ ] `aria-live` on: answer stream (polite), run status (polite), error toasts (assertive). Feed summarized, not read row-by-row.
- [ ] State chips: icon + label always (no color-only meaning) — verify in grayscale screenshot.
- [ ] Reduced-motion pass with OS setting enabled, every view.
- [ ] Landing headline copy tested at 320px (no overflow; `text-wrap: balance`).

## 11. Build Order

Sequenced for the same "demoable every Friday" discipline as PLAN.md. Frontend
work starts mid-week-2 (against fixture event logs — the replay-first
architecture means **no UI work blocks on the backend**).

**W2.5 — Foundations (2 days):** Next.js scaffold, tokens → Tailwind theme,
Plex fonts, shell (top bar, rail, drawer skeleton), command palette, fixture
event logs + the Zustand event store with replay source, Storybook with the
vocabulary components (StatusChip, AgentBadge, CostTag, FeedRow) in all states.

**W3.1–3.2 — Mission Control:** roster, feed (virtualized), territory map, run
footer, replay scrubber; live WS source wired; stress fixture (200 ev/s).

**W3.3–3.4 — Atlas:** Sigma canvas + semantic zoom against a real fastapi graph
export, inspector, search/filters, code panel; walkthrough overlay if on pace
(else W4).

**W3.5 — Chat:** threads, streaming answers, citation chips + code panel,
transparency strip, escalation card.

**W4.1 — Landing page** (brand register day): hero with replay embed, cost
chart from real eval data, verification strip, eval table.

**W4.2 — Polish pass:** run `/impeccable critique` per view, then `polish`;
contrast + reduced-motion + keyboard audits (§10); empty/error states sweep
(§8); perf budgets (§9).

**W4.3 — Demo:** record the 2-minute video against a live index of fastapi;
OG images per route; deep links verified.

**Definition of Done per view:** all §8 states exist · §10 items pass · budget
in §9 met · every component in Storybook with fixture data · reduced-motion
verified · screenshot in PR.

## 12. Demo & Asset Plan

The 2-minute video script the UI must serve: (1) paste fastapi URL → roster
spawns, territory lights up, cost ticks (30s) · (2) critic rejects a claim
on-camera (10s) · (3) atlas semantic zoom → node inspect → verified annotation
(25s) · (4) local question → instant cited answer, click citation → exact lines
(20s) · (5) escalated question → inline explorer → "graph updated" line →
re-ask → now instant + cheap (25s) · (6) cost chart close (10s). Every beat in
this script maps to a named spec element above — if a beat demos poorly, the
spec, not the script, is wrong.
