# Handoff: CreativeGate — Creative Quality Gate System

## Overview
CreativeGate is a system that runs every creative asset (video, image, copy) through a
pipeline of **deterministic checkers → judge ensembles → saliency prediction → spend
calibration**, then issues a PASS / WARN / FAIL verdict before the asset goes live.

This bundle delivers four connected surfaces:
1. **Marketing home** — product landing page.
2. **Ingestion Hub** — paste/drop an asset to run the gate.
3. **Verdict Dashboard** — data-dense telemetry for a single run.
4. **Calibration Harness** — sim-vs-live-spend trajectory analysis.

## About the Design Files
The file in this bundle (`CreativeGate.dc.html`) is a **design reference created in HTML** —
a working prototype showing the intended look, layout, and behavior. It is **not production
code to copy directly**. It is authored as a "Design Component" (a streaming HTML format with
a `<x-dc>` template + a `Component` logic class); treat that structure as scaffolding, not as
something to reproduce.

Your task is to **recreate these designs in the target codebase's existing environment**
(React, Vue, Svelte, etc.) using its established component library, styling system, routing,
and state patterns. If no frontend environment exists yet, choose the most appropriate
framework for the project and implement the designs there. All four surfaces should live under
one app shell with client-side routing between them.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, and interactions are specified.
Recreate the UI pixel-accurately using the codebase's existing primitives, matching the exact
tokens listed below. The one exception is imagery — the media/saliency areas use striped
placeholders (see Assets).

---

## Design Tokens

### Colors
| Token | Hex | Usage |
|---|---|---|
| ink (primary dark) | `#0F1115` | Text, dark panels, dark buttons, ledger drawers, footer, dashboard rail |
| ink raised | `#1B1E24` | Active run-list row background |
| ink border | `#23262D` / `#2A2E36` | Borders inside dark surfaces |
| ink log bg | `#17191F` | Raw-log code block background (dark) |
| paper (primary light) | `#F9FAFB` | App background |
| white | `#FFFFFF` | Cards, panels, inputs on light surfaces |
| border | `#E5E7EB` | 1px micro-borders / grid lines |
| border-soft | `#F3F4F6` | Interior row dividers |
| text-body | `#4B5563` | Body copy |
| text-muted | `#6B7280` | Secondary text |
| text-faint | `#9CA3AF` | Mono labels, captions |
| accent green (success) | `#059669` | Verify/PASS, accents, sim line, primary CTA on ingest |
| green dot | `#10B981` | PASS status dot |
| green bar | `#059669` | Judge bars ≥85 |
| amber (warn) | `#D97706` | WARN flags, drift markers |
| amber text | `#B45309` | WARN badge text |
| amber dot | `#F59E0B` | WARN status dot |
| red (fail) | `#DC2626` | FAIL |
| red text | `#DC2626` | FAIL badge text |
| red dot | `#F87171` | FAIL status dot |
| scrollbar thumb | `#D1D5DB` | — |

Status badge/pill backgrounds are translucent tints of the status color:
- PASS bg `rgba(5,150,105,0.12)`, text `#047857`
- WARN bg `rgba(217,119,6,0.16)`, text `#B45309`
- FAIL bg `rgba(220,38,38,0.14)`, text `#DC2626`

Saliency heatmap hotspots: `radial-gradient(circle, rgba(5,150,105,0.5) 0%, transparent 70%)`
(green focus) and `rgba(217,119,6,0.42)` (amber secondary).

### Typography
- **Display / UI sans:** `Space Grotesk` (weights 400, 500, 600, 700).
- **Data / labels / code:** `JetBrains Mono` (weights 400, 500, 700).
- Both loaded from Google Fonts.

Type scale (px, all with tight tracking on headings):
| Role | Size | Weight | Tracking | Notes |
|---|---|---|---|---|
| Hero H1 (home) | 72 | 700 | -0.035em | line-height 0.98 |
| Page H1 (ingest) | 44 | 700 | -0.03em | — |
| Section H2 | 32 | 700 | -0.02em | — |
| Dashboard H1 (asset name) | 26 | 700 | -0.02em | — |
| Calibration H1 | 30 | 700 | -0.02em | — |
| Stat number (big) | 34 | 700 | -0.02em | % sign at 18px `#9CA3AF` |
| Proof stat (home) | 52 | 700 | -0.03em | — |
| Mega footer wordmark | clamp(64px,15vw,240px) | 700 | -0.05em | line-height 0.86 |
| Body / lede | 19 | 400 | — | line-height 1.55, `#4B5563` |
| Body small | 14–16 | 400/500 | — | — |
| Mono label | 10–12 | 400/500 | 0.08–0.14em | UPPERCASE, `#9CA3AF` |
| Nav item | 14 | 500/600 | — | — |

### Spacing / Radius / Misc
- Card/panel radius: `12px` (large cards `14px`, buttons `9px`, chips/badges `5–8px`, inputs `8–12px`).
- Micro-border: `1px solid #E5E7EB`. Dashed dropzone: `1.5px dashed #D1D5DB`.
- Top bar height: `66px`, sticky, `rgba(249,250,251,0.86)` + `backdrop-filter: blur(10px)`, 1px bottom border.
- Dashboard grid: `288px` dark rail + `1fr` content.
- Content max-width: `1220px` (home/calibration), `760px` (ingest).
- Shadow (subtle): `0 1px 2px rgba(15,17,21,0.04)` on the paste bar.
- Striped placeholder fill: `repeating-linear-gradient(135deg, #F3F4F6 0 14px, #EDEEF1 14px 28px)`.

### Animations / Keyframes
- `cg-marquee`: `translateX(0)` → `translateX(-50%)`, `34s linear infinite` (tech ticker; duplicate the item list twice inside a `width: max-content` flex track).
- `cg-pulse`: opacity `1 → 0.35 → 1`, `2s ease-in-out infinite` (the "gate online" status dot).

---

## Screens / Views

### 1. App shell (all views)
- **Top bar** (sticky, 66px): left = logo (26px `#0F1115` rounded square containing a 10px
  emerald-bordered square) + `CreativeGate` wordmark (17px/700) + `v3.2` mono pill; center =
  nav (Home, Ingest, Dashboard, Calibration) — active item has `#0F1115` bg / `#F9FAFB` text /
  600 weight, inactive is transparent / `#4B5563` / 500; right = "gate online" mono label with
  a pulsing 7px emerald dot + a 30px `#0F1115` circular `OK` avatar.
- Clicking the logo returns Home. Nav routes between the four views.

### 2. Marketing Home
- **Hero**: 2-col grid (1.35fr / 1fr, `align-items: end`, 92px top padding). Left: mono kicker
  `// CREATIVE QUALITY GATE`, H1 "Nothing ships until it clears the gate.", 19px lede, then two
  buttons — primary `#0F1115` "Open ingestion hub →" and ghost (1px `#D1D5DB` border) "View a
  sample verdict". Right: a **micro-border spec card** listing the 4 pipeline stages, each row:
  mono index (`01`…), 8px emerald square, stage name, mono meta on the right; rows separated by
  `1px #F3F4F6` top borders.
- **Tech marquee**: full-bleed strip (white, 1px top+bottom border, 18px vertical padding),
  continuous horizontal scroll of mono technology names separated by `#D1D5DB` slashes
  (FastAPI / Pydantic / Gemini Flash / Deterministic Checkers / Judge Ensembles / Saliency
  Predictor / Spend Calibration / OCR Guardrails). Duplicated twice for a seamless loop.
- **"The gate, in four passes"**: H2 + mono breadcrumb `ingest → gate → judge → calibrate`, then
  a 4-column grid inside one `1px #E5E7EB` rounded container with column dividers. Each cell:
  mono step label (`01 · Ingest`), a large gap, title (18px/600), body (14px `#6B7280`).
- **Proof stats**: 3-col row, big numbers (`1.2M` assets gated, `94%` mean ensemble certainty,
  `0.93` sim ↔ live correlation) with mono uppercase captions.
- **Oversized footer**: `#0F1115` bg, `#F9FAFB` text. Top row = a tagline column + 3 link columns
  (Product / Pipeline / Company). Then a giant `CreativeGate` wordmark
  (`clamp(64px,15vw,240px)`, above a `1px #23262D` top border). Bottom mono line: copyright +
  "All verdicts calibrated against live spend."

### 3. Ingestion Hub (max-width 760px, centered)
- Centered header: mono kicker `// INGESTION HUB`, H1 "Drop an asset. Get a verdict.", 16px sub.
- **Fast-paste bar**: single row, 1px `#D1D5DB` border, radius 12px, subtle shadow. A `›` mono
  prompt glyph, a full-width text input (placeholder shows a CDN URL "— or a JSON config link"),
  and an emerald **"Run gate →"** button (`#059669` bg, white text). Submitting routes to the
  dashboard.
- **Dropzone**: 1.5px dashed border, striped bg, 48px padding, centered. "Drag & drop a creative
  asset" (15px/600) + mono line ".mp4 · .mov · .png · .jpg · .txt · up to 512 MB".
- **Profile row**: 1px-border white bar — "Evaluation profile" + a mono pill "Broadcast v3 ·
  default", and an emerald "Change profile" text button.
- **Recent runs**: header ("Recent runs" + mono "last 60 min") over a 1px-border white list.
  Each row: status dot, mono run id (fixed 72px), asset filename (ellipsis, flex-1), mono type,
  status badge, mono relative time. Clicking a row selects that run and routes to the dashboard.

### 4. Verdict Dashboard (grid: 288px rail + content)
- **Run-list rail** (`#0F1115`, scrollable): header "SIMULATION RUNS" + count. Each run card:
  status dot + mono id + mono time (right), asset filename (500), then mono `TYPE · score NN`.
  Active card has `#1B1E24` bg + `inset 0 0 0 1px #2A2E36`. Click selects → drives the whole
  right panel.
- **Run header**: mono id + type pill + profile; H1 = asset filename; on the right a **verdict
  box** tinted by status (bg/text from the status tints) with a dot, "VERDICT" mono label, and
  big PASS/WARN/FAIL (20px/700).
- **Stat blocks**: 4-col grid of 1px-border white cards — *Simulated Quality Floor* (88.4%, "▲
  above launch min" in emerald), *Historical Base Correlation* (0.94, "r · vs live spend"),
  *Ensemble Certainty* (96%, "5-judge agreement"), *Runtime* (2.10s, "wall clock"). Each: mono
  uppercase label + 34px number + mono sub-line.
- **Split panel** (1.15fr / 1fr):
  - *Saliency prediction* card: header + mono "attention model · v4"; a 16:9 striped viewport
    with 3 radial-gradient heatmap hotspots (2 green, 1 amber) and a centered mono chip "creative
    asset · 1920×1080"; footer with 3 mini-stats (Focus hit-rate 86%, CTA in first fixation Yes,
    Clutter index 0.31).
  - *Judge ensemble* card: header + mono "5 models · Gemini Flash"; 5 horizontal bars
    (Composition 91±4, Message clarity 83±9, Emotional resonance 77±12, Brand fit 94±3, Saliency
    alignment 86±6). Bar track `#F3F4F6`, fill color by score: ≥85 emerald, 70–84 amber, <70 red;
    width = score%. Label + mono `value ±spread`.
- **Deterministic gate ledger**: header ("Deterministic gate ledger" + hint "click a row to
  expand the raw log"), a mono **filter input** ("filter rules…"), and **filter chips** All /
  Pass / Warn / Fail (each shows a live count; active chip = `#0F1115` bg / white). Below, a
  vertical stack of **dark accordion drawers** (`#0F1115`, radius 10px). Row header: status dot,
  rule name (flex-1), mono gate label, status badge, and a `+` / `×` toggle glyph (18px mono).
  Clicking toggles open; open body (indented 40px left) shows the detail sentence (`#D1D5DB`)
  and a mono raw-log block (`#17191F` bg, 1px `#23262D` border, `white-space: pre-wrap`).

### 5. Calibration Harness (max-width 1220px)
- Header: mono kicker `// CALIBRATION HARNESS`, H1 "Cheap simulations vs. real spend", 15px
  explanatory paragraph; on the right, 3 small 1px-border stat cards (Sim↔live r 0.93, Tier
  coverage 96%, Drift +2.1%).
- **Trajectory chart** (1px-border white card): legend row (Live-spend actual = `#0F1115` line,
  Simulated evaluation = `#059669` line, Calibration band = translucent green). SVG `viewBox
  0 0 960 380`, plot inset L92 R44 T44 B54.
  - Y axis = **exponential spend index** with 4 gridlines/labels: `$10k+`, `$1,000`, `$100`,
    `$10` (top→bottom), 1px `#E5E7EB` lines, mono `#9CA3AF` labels.
  - X axis = 12 weekly ticks `W1…W12`, mono `#9CA3AF`.
  - **Calibration band**: filled area between the two lines, `rgba(5,150,105,0.13)`.
  - **Divergence markers**: dashed amber vertical guides (`rgba(217,119,6,0.5)`,
    `strokeDasharray 3 3`) at weeks where |sim − actual| > 0.055.
  - Two 2.5px polylines, round joins/caps: actual `#0F1115`, simulated `#059669`.
- **Tier readout table** (1px-border white card): 5-col grid header (Spend tier / Sim verdict /
  Live outcome / Agreement / Status), then rows: `$10 · simulated` PASS/PASS/0.96/PASS,
  `$100 · early live` PASS/PASS/0.93/PASS, `$1,000 · scaled` WARN/PASS/0.84/WARN,
  `$10k+ · flagship` PASS/PASS/0.91/PASS. Status column uses the tinted badge.

---

## Interactions & Behavior
- **Routing**: top-nav buttons and logo switch between home / ingest / dashboard / calibration
  (single-page, no reload). Default landing = home.
- **Ingest → Dashboard**: "Run gate →" and clicking any recent-run row navigate to the dashboard
  (a recent-run click also selects that run).
- **Run selection**: clicking a rail card updates the run header, verdict box, and all 4 stat
  blocks for that run. (In the prototype the ledger/judges/saliency are shown for the selected
  run; wire them to real per-run data in production.)
- **Ledger live filtering**: the text input filters ledger rows by rule name (case-insensitive,
  substring), combined with the active status chip (all/pass/warn/fail). Chip counts reflect the
  full ledger, not the filtered subset.
- **Accordion**: each ledger row toggles open/closed independently; glyph flips `+` ↔ `×`.
- **Marquee**: infinite CSS scroll; pauses on nothing (purely decorative).
- **Status pulse**: "gate online" dot pulses via `cg-pulse`.
- No error/loading states are designed yet — add per your app's conventions.

## State Management
Needed state:
- `view`: `'home' | 'ingest' | 'dashboard' | 'calibration'` (current route). Default `'home'`.
- `paste`: string — ingest paste-bar value.
- `selected`: index/id of the currently selected run (drives dashboard header + stats).
- `filter`: `'all' | 'pass' | 'warn' | 'fail'` — ledger status filter.
- `query`: string — ledger rule-name search.
- `open`: map of ledger-rule → boolean (which drawers are expanded).

Data models to fetch in production:
- **Run**: `{ id, asset, type: VIDEO|IMAGE|COPY, profile, status: pass|warn|fail, score, floor,
  corr, cert, exec, time }`.
- **Ledger rule**: `{ rule, gate, status: pass|warn|fail, detail, log }`.
- **Judge dimension**: `{ k (name), v (score 0–100), spread }`.
- **Calibration**: 12-point `sim[]` + `actual[]` series (0–1 fractions on a log-spend Y),
  plus the tier table rows.

## Assets
- **Fonts**: Space Grotesk + JetBrains Mono (Google Fonts) — swap for the codebase's equivalent
  if it self-hosts fonts, but keep a grotesque-sans + monospace pairing.
- **Icons**: none as image files — the few glyphs used are Unicode (`›`, `→`, `▲`, `×`, `+`, `·`,
  `±`) and simple CSS squares/dots. Replace with the codebase's icon set if desired.
- **Imagery placeholders**: the saliency viewport is a **striped placeholder** with radial
  heatmap overlays, not a real asset. In production, render the actual creative frame with a
  real saliency heatmap layered over it.
- No logo image file — the logo is built from CSS (rounded square + inner bordered square).

## Files
- `CreativeGate.dc.html` — the complete high-fidelity prototype (all four views, nav, live
  filtering, expandable ledger, calibration chart). This is the single source of truth for the
  design; open it in a browser to see every interaction.
