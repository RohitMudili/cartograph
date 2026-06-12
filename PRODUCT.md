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

Cartograph turns a GitHub repo into a persistent knowledge graph built by a
visible fleet of agents, then answers questions against that graph with verified
`file:line` citations at ~1/50th the cost of re-exploration. Success looks like:
a stranger indexes their own repo unassisted and gets a correct, cited answer in
under 5 minutes — and an AI engineer watching the demo says "oh, that's actually
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
