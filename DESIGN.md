# Design System — Cartograph

> **Concept: "instrument panel at night."** Dark glass surfaces, amber telemetry,
> mono numerals, calm precision. The mood lives in the amber primary, the IBM Plex
> instrument-heritage typography, and the live data — never in tinted backgrounds
> or decoration. Status: seed (pre-implementation); re-run `/impeccable document`
> once real tokens exist in code.

## Theme

Dark-only in v1 (the product is "watching agents work at night"; the demo, the
IDE-adjacent context, and the glowing telemetry all want black glass). A light
theme is a deliberate v2 item, not a toggle bolted on late.

## Color

All tokens OKLCH. Strategy: **Restrained** on task surfaces (Atlas, Chat — amber
≤ 10% of pixels), **Committed** on Mission Control and the landing hero, where
amber telemetry carries the identity.

### Core tokens

```css
:root {
  /* surfaces — pure neutral black glass; NO warm tint in backgrounds */
  --bg:          oklch(0.10 0 0);            /* app body */
  --surface:     oklch(0.15 0.004 91.3);     /* cards, panels, code panel */
  --surface-2:   oklch(0.13 0.003 91.3);     /* rails, toolbars, drawer (2nd neutral) */
  --border:      oklch(0.28 0.008 91.3);     /* 1px hairlines */
  --border-hi:   oklch(0.40 0.02  91.3);     /* focused/active borders */

  /* ink */
  --ink:         oklch(0.93 0.012 91.3);     /* body text — ≥7:1 vs --bg */
  --muted:       oklch(0.65 0.015 91.3);     /* secondary text — ≥4.5:1 vs --bg */
  --faint:       oklch(0.48 0.012 91.3);     /* disabled/tertiary — large text & icons only */

  /* brand */
  --primary:     oklch(0.84 0.165 91.3);     /* amber — live, active, primary action, cost */
  --on-primary:  oklch(0.15 0.03  91.3);     /* near-black on amber (pale fill → dark text) */
  --primary-dim: oklch(0.84 0.165 91.3 / 0.14); /* amber wash for selected rows/chips */
  --accent:      oklch(0.62 0.13  230);      /* radar blue — links, info, route badges */
  --on-accent:   oklch(0.97 0.005 230);      /* white on saturated mid-tone fill */

  /* semantic state (always paired with icon + label, never color alone) */
  --verified:    oklch(0.72 0.13 150);       /* green — critic-passed, citation-verified */
  --rejected:    oklch(0.60 0.16 25);        /* red — critic-rejected, errors */
  --pending:     oklch(0.70 0.10 91.3);      /* dim amber — unverified/in-flight */

  /* glow — the ONLY shadow vocabulary; used on live elements, sparingly */
  --glow-live:   0 0 12px oklch(0.84 0.165 91.3 / 0.25);
  --glow-focus:  0 0 0 2px oklch(0.10 0 0), 0 0 0 4px var(--primary);
}
```

### Agent identity ramp (categorical)

Explorer territories, event-feed attribution, atlas region tints. Desaturated so
amber stays the star; each pairs with a glyph (▲ ◆ ● ■ ✦ ⬟) so identity survives
color blindness.

```css
--agent-1: oklch(0.72 0.09 250);  /* slate blue   */
--agent-2: oklch(0.72 0.09 160);  /* sage green   */
--agent-3: oklch(0.72 0.09 320);  /* orchid       */
--agent-4: oklch(0.72 0.09 50);   /* clay         */
--agent-5: oklch(0.72 0.09 200);  /* teal         */
--agent-6: oklch(0.72 0.09 0);    /* rose         */
/* planner/synthesizer/critic use role styling (amber/ink), not the ramp */
```

### Usage rules

- Backgrounds are chroma-0 black; warmth enters only through amber elements.
- Amber = "alive or actionable": live indicators, running agents, primary
  buttons, selection, cost ticker. Never as decoration on static content.
- Text on amber fills: `--on-primary` (dark). Text on accent/verified/rejected
  fills: white (`--on-accent`). Helmholtz-Kohlrausch rule: saturated mid-tones
  get white text even when WCAG would pass dark.
- `--faint` never carries body copy — icons, disabled labels, ≥18px text only.
- No gradients anywhere in v1 except the landing hero's single radial vignette
  (a light source, not a color ramp).

## Typography

One superfamily — IBM Plex (instrument-panel heritage; Sans and Mono share DNA).
No display font; the landing page earns scale through weight and size, not a
second family.

```css
--font-ui:   "IBM Plex Sans", system-ui, sans-serif;
--font-mono: "IBM Plex Mono", ui-monospace, monospace;
```

| Token | Size / line | Use |
|---|---|---|
| `text-xs` | 12 / 16 | timestamps, chip labels |
| `text-sm` | 13 / 18 | feed rows, table cells, code |
| `text-base` | 14 / 21 | body, chat answers (cap 70ch) |
| `text-md` | 16 / 24 | panel titles |
| `text-lg` | 20 / 28 | view headers |
| `text-xl` | 24 / 30 | repo name, big counters |
| `display` (landing only) | clamp(2.5rem, 6vw, 4.5rem) / 1.05 | hero; weight 650, tracking −0.025em, `text-wrap: balance` |

Rules: fixed rem scale in-app (no fluid type in product register). **All numerals
that update live (tokens, cost, line numbers, timers) are Plex Mono with
`font-variant-numeric: tabular-nums`** — nothing shifts width as it ticks. Code
is always Plex Mono 13/19. Weights: 400/500/600 only (+650 display on landing).

## Spacing, Radius, Elevation

- 4px base grid: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64. Density: feed rows 32px,
  table rows 36px, panel padding 16, view gutters 24.
- Radius: `--r-sm: 4px` (chips, inputs), `--r-md: 8px` (cards, panels),
  `--r-lg: 12px` (command palette, dialogs). Nothing rounder; no pills except
  status chips.
- Elevation = border + subtle lift, not drop shadows: raised surfaces get
  `--surface` + 1px `--border`. The amber/focus glows are the only shadows.
- z-index scale: `--z-rail: 10, --z-drawer: 20, --z-sticky: 30,
  --z-palette-backdrop: 40, --z-palette: 50, --z-toast: 60, --z-tooltip: 70`.

## Motion

Energy: **calm with a live pulse**. UI transitions 150–200ms `cubic-bezier(0.22,
1, 0.36, 1)` (ease-out-quint). Data choreography is where motion lives:

- Feed events enter with 12px rise + fade, 180ms, stagger 40ms (cap 5 per frame).
- Live agent dot: 2s opacity pulse (0.6→1). The only looping animation allowed.
- Graph camera moves 400ms ease-out-quint; node territory "light-up" 250ms fill.
- Counters tween numerically (no slot-machine effects).
- No page-load orchestration in-app; landing hero gets one entrance sequence.
- `prefers-reduced-motion`: pulses stop (dot stays solid), entrances become
  120ms fades, graph camera jumps with a crossfade. Content never gated on
  animation.

## Components (inventory + state contract)

Every interactive component ships all states: default / hover / focus-visible /
active / disabled / loading / error. Loading = skeleton shimmer on `--surface`,
never centered spinners. Empty states teach ("No questions yet — try ⌘K →
'where is auth handled?'").

Core set (shadcn/ui as the headless base, restyled to tokens): Button (primary
amber / secondary outline / ghost), Input + Textarea, Command Palette (⌘K),
StatusChip (verified ✓ / pending ◌ / rejected ✕ — icon + label + color),
AgentBadge (glyph + name + state), RouteBadge (local/global/escalated), CostTag
(mono, amber), Tabs, Tooltip, Toast, Skeleton, CodePanel (Plex Mono, line
numbers, highlight range), GraphCanvas, FeedRow, Timeline scrubber, Drawer,
DataTable (virtualized), CommitBadge (`fastapi @ a1b2c3 · 2 commits behind`).

## Layout

- App shell: 56px top bar (repo switcher, commit badge, run status, cost ticker,
  ⌘K hint) + 48px icon rail (Run / Atlas / Chat / Walkthrough / Settings) +
  content. Right-side **telemetry drawer** (360px, toggleable, `[` key) available
  in every view.
- Landing page is a separate brand-register layout: single column, max-w 1100px,
  generous vertical rhythm; no app chrome.
- Breakpoints: desktop-first (this is a desk tool). ≥1280 full shell; 768–1279
  drawer becomes overlay, atlas inspector becomes bottom sheet; <768 read-only
  mode (chat + answers + landing) with an honest "Cartograph is a desktop tool"
  note on Run/Atlas.

---

## As implemented (2026-07-12 addendum)

The tokens live in `frontend/app/globals.css` (`@theme`). Additions since the
seed spec, all in service of the same concept:

- `--color-surface-3: oklch(0.18 0.005 91.3)` — the hover/raised step. Elevation
  in the app is **stepped surface lightness** (bg 0.10 → surface-2 0.13 →
  surface 0.15 → surface-3 0.18); hairlines only where a step isn't enough.
- Motion vocabulary: `--ease-out: cubic-bezier(0.23,1,0.32,1)` (entrances,
  camera, reveals) and `--ease-drawer: cubic-bezier(0.32,0.72,0,1)` (the code
  panel). Built-in CSS easings are too weak — never `ease-in` on UI.
- `pressable` utility — 140ms `scale(0.97)` on `:active` for every pressable
  element (buttons, chips, rail items, session rows). The interface hears the
  click.
- Keyboard actions are never animated (1–4 view switch, `/` focus, `f` search
  are instant). Rail tooltips delay 300ms in, disappear instantly.
- Atlas edge kinds carry **line styles**, not just color: imports solid, calls
  dashed, inheritance dotted — the map reads in grayscale.
- The one glow on the Atlas map is the selected node (amber, shadowBlur 16);
  annotation-bearing nodes carry a thin amber ring. Everything else is flat.
