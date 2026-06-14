# Product

## Register

product

> Exception: the public landing page (`/`) is a **brand** surface — design IS the
> product there. Everything behind it (`/r/*`) is product register: design serves
> the task.

## Users

- **AI engineers & hiring managers** evaluating the project as a portfolio piece.
  Context: skimming a demo video or clicking around a live deploy for 2–5 minutes.
  Job: "convince me this person understands agents, fast."
- **Developers onboarding onto an unfamiliar codebase** (new hires, OSS
  contributors, consultants). Context: focused desk work, usually dark IDE
  alongside. Job: "build a correct mental model of this repo in minutes, with
  receipts (citations), not vibes."
- **Returning users** asking follow-up questions. Job: instant, cheap, trustworthy
  answers — the tool should feel like consulting a map, not commissioning a survey.

## Product Purpose

Cartograph lets you **watch a fleet of agents map a GitHub repo live** — then
answers questions against the resulting knowledge graph with **adversarially
verified `file:line` citations** and published accuracy evals. The persistent
graph also makes follow-up questions cheap, but the headline is the visible
exploration and the verified, evaluated answers — not the graph or the chat
(both now commodity; see Competitive Landscape). Success looks like: a stranger
indexes their own repo unassisted and gets a correct, cited answer in under 5
minutes — and an AI engineer watching the demo says "oh, that's actually
well-architected."

## Brand Personality

**Instrumented · Precise · Alive.**

The feel of a flight deck or observatory at night: dark glass, amber telemetry,
calm confidence. The interface never hypes — it *shows*. Real agent activity,
real token counts, real verification verdicts. Warmth comes from the amber light
and the liveliness of the agents working, never from decoration. Voice in copy:
plain, technical, quietly confident; numbers are always real and always sourced.

## Anti-references

- **Purple-gradient AI SaaS** (gradient text, sparkle emoji, "✨ AI-powered").
  The single most saturated aesthetic in the category. Total ban.
- **Terminal-green hacker dashboards** — the second-order reflex for "dark dev
  tool." Our dark is an instrument panel, not a Matrix cosplay.
- **Cream/beige editorial SaaS** (the 2026 AI default light theme).
- **Generic chatbot UI** — a centered chat bubble column with an input box. The
  chat view must feel like a research console (citations, routes, costs, the
  consulted subgraph), not ChatGPT-with-a-logo.
- **Fake-it dashboards** — decorative charts, invented numbers, simulated agent
  activity. If it's on screen, it's real data from the backend.

## Competitive Landscape (market reality, June 2026)

The "codebase → knowledge graph → grounded answers" space is **validated and
active** — which is good (the problem is real, no interviewer asks "why would
anyone want this") and sobering (the core idea is no longer novel). Honest map:

**Direct / close players:**

- **Greptile** — funded startup; whole-codebase reasoning, NL queries, onboarding
  + PR review. Highest overlap on the core value prop. Commercial, polished.
- **Sourcegraph Cody** — enterprise code search + AI assistant; entrenched.
- **GitNexus** (open source, Aug 2025) — the closest architectural twin. Independently
  built tree-sitter → code knowledge graph with the *same* edge types we planned
  (calls/imports/inheritance), cluster detection, and incremental reindex, exposed
  via MCP to Claude Code/Cursor. **Our static-graph-first GraphRAG insight is not
  novel anymore — GitNexus shipped it ~10 months before us.**
- **CodeScene / Emerge / CodeLayers** — codebase visualization & force-directed
  architecture graphs. Overlap on the Atlas view specifically.

**What is now commodity (do NOT pitch these as differentiators):**

- A tree-sitter code graph with calls/imports/inheritance edges.
- "Chat with your codebase" / NL queries over a repo.
- Multi-agent *parallel coding* (every major player shipped this Feb 2026).
- Live/watch-mode graph updates — explicitly described as *table stakes* in 2026.

**What is still genuinely unoccupied — these are our real edges, lean into them:**

1. **Watch agents explore as the product.** Everyone else hides indexing behind a
   progress bar. Nobody makes the live, beautiful multi-agent exploration —
   *with the verification loop visible on screen* — the centerpiece. Hardest for
   a competitor to copy, most demo-able thing we have.
2. **Verified citations as a first-class, adversarially-checked feature with
   PUBLISHED precision/recall evals.** Competitors say "NL queries"; none publish
   a citation-accuracy scoreboard. This is the credibility moat for a portfolio.
3. **Standalone "paste a URL, watch it happen" web experience.** GitNexus is an
   MCP server for your editor; Greptile/Cody are platforms. The instant,
   zero-setup, *visual* "watch a stranger's repo get mapped in 2 minutes" is its
   own distinct thing.

**Positioning rules that follow from this:**

- **Never claim the static-graph / GraphRAG-for-code insight is novel.** It isn't.
  Frame the writeup as *"how I'd architect this class of system, with the
  engineering rigor — evals, adversarial verification, cost accounting — that
  shipped products skip."* GitNexus existing is evidence our architecture is
  sound, not a threat to the portfolio goal.
- **Lead every demo and the landing page with the two surviving differentiators**
  (live exploration theater + published citation evals), not with "chat" or "the
  graph" — those read as me-too.
- The goal is **demonstrating engineering depth**, not winning market share against
  a funded startup. A crowded market *helps* that goal.

## Design Principles

1. **The work is the spectacle.** The most attractive thing we own is real agent
   activity. Render it faithfully and beautifully; never simulate or embellish it.
   Mission Control is theater, but documentary theater.
2. **Trust is rendered.** Verification state is a first-class visual dimension:
   verified, unverified, and rejected claims must be distinguishable at a glance
   everywhere they appear (feed, atlas annotations, chat citations).
3. **Cost is part of the interface.** Token spend and dollar cost are always
   visible, always real, formatted with care (tabular numerals). The economics
   ARE a feature; the UI flexes them.
4. **Disappear into the task.** Atlas and Chat are tools in the Linear mold:
   dense, calm, keyboard-first, zero decorative motion. Spectacle is earned only
   where the data itself is the show (Mission Control, the graph).
5. **One vocabulary.** One status language (colors, icons, labels) shared across
   agent cards, feed events, atlas nodes, and chat citations. The same state never
   looks two ways.

## Accessibility & Inclusion

- WCAG 2.1 AA: body text ≥ 4.5:1 against surfaces (audited — dark themes fail
  this more often than light), focus visible on every interactive element,
  full keyboard operability including the graph (search + list fallback).
- **State is never encoded by color alone** — verified/unverified/rejected each
  carry an icon + label, not just green/amber/red (color-blind safety).
- `prefers-reduced-motion`: all choreography (feed entrances, graph transitions,
  glow pulses) degrades to crossfades or instant state changes; live data still
  updates.
- Live regions (`aria-live=polite`) for streamed answers and run status; the
  event feed is virtualized but screen-reader summarized ("explorer_3 verified
  finding 42").
- English-only v1; copy avoids idiom so non-native readers aren't taxed.
