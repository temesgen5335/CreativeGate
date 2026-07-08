# memory.md — Build history, decisions, and measured results

> The living record of what was built, in what order, why, and what we learned.
> **Append to this file whenever you make a non-obvious decision, deviate from
> the charter, or measure something worth remembering.** Newest entries at the
> bottom of each section. Never rewrite history here — this is an audit trail,
> same discipline as the calibration store.

## Build history (v0.1 vertical slice — July 2026)

Built in one session as 9 logically-separated commits:

| Commit | What |
|---|---|
| `991399b` | Scaffold: pyproject (hatchling, uv), README with funnel diagram |
| `36a05f0` | Core schemas — the stable contract |
| `dee5e72` | Provider slots with keyless degradation + shared feature extractor |
| `5f533dc` | The three v0.1 rungs behind one plugin interface |
| `4584aeb` | SQLite repository behind a thin storage interface |
| `f66a29d` | Calibration harness + synthetic world |
| `de821af` | Funnel engine: cost-ordered filtering, fusion, next-test |
| `c87fe73` | Product surfaces: profiles, HTML report, CLI, API |
| `51e53f6` | Test suite with the safety rails as its spine (45 tests) |

## Design decisions and their reasons

**D1 — Validity is stamped by the framework, not by rungs.**
`Rung.stamped_validity()` in `rungs/base.py` builds `Validity` strictly from
the calibration store via `ctx.calibration_lookup`. Rungs *cannot* self-assert
trustworthiness. This makes safety rail "no unearned validity" structural
rather than conventional. If you add a rung, do not override this.

**D2 — Deliberate charter deviation: no per-rung `calibrate()` method.**
The charter's rung interface included `calibrate(records) -> CalibrationReport`.
We centralized all calibration math in `CalibrationHarness` instead, because
the math is identical across rungs and central ownership is what makes D1
enforceable. The charter's *intent* (per-rung, per-segment, per-modality
calibration records) is fully preserved. If a future rung genuinely needs
custom calibration math (e.g. reliability diagrams for probabilistic rungs),
extend the harness, don't decentralize.

**D3 — Gates return `score=None`, never a quality number.**
The deterministic gate passing all rules must not be confusable with "is
good". Fusion skips `score=None` results entirely; gates contribute evidence
and eliminations only.

**D4 — Judge is pairwise-only, position-debiased, outcome-weighted.**
No absolute scoring mode exists on purpose (judges are unreliable at it).
Anchors are picked deterministically by outcome quantiles
(`judge.select_anchors`); A/B order alternates across ensemble passes to
cancel position bias; wins against high-CTR anchors count more (weight
0.5–1.5 by outcome rank).

**D5 — Keyless degradation is a first-class path, not a stub.**
`NullLLM` is a deterministic heuristic comparator; embeddings fall back to
TF-IDF+SVD. Both are honestly labeled `provider_fidelity="degraded"` in every
result and surfaced in the next-test recommendation ("confidence limited by
degraded keyless providers"). CI and the demo run entirely keyless.

**D6 — One shared, versioned feature extractor (`features.py`).**
Both the performance predictor and the synthetic world consume it. This
guarantees the "physics" the world generates from and the features the
predictor learns from can only drift apart deliberately. `FEATURE_VERSION`
must be bumped on any change.

**D7 — Fusion weight = measured Spearman, floored and cut on drift.**
`harness.fusion_weight()`: 0.0 when uncalibrated, n < 5, r < min_weight_r
(profile config, default 0.1), or r negative; halved when drift detected.
When *all* weights are zero, fusion still returns an unweighted mean but
labels it `DIRECTIONAL ONLY` with a deliberately wide band — honest, not
useless.

**D8 — Band width has three real sources.**
`engine/fusion.py`: rung-internal ensemble variance (propagated through
weights) + calibration weakness (1 − r²) + coverage penalty (little total
calibrated weight ⇒ wide band). Do not "tune" the band to look better; it is
the honesty signal.

**D9 — SQLite behind `storage/repo.py`; calibrations append-only.**
No ORM, no migrations framework — deliberate. The Postgres upgrade is a
reimplementation of ~10 repository methods. The `calibrations` table is
append-only (audit trail); `latest_calibration` reads the newest row.

**D10 — Predictor trains lazily and caches per fingerprint.**
`_MODEL_CACHE` keyed by (ground-truth set name+size, metric, seed, config,
feature version). Scoring N artifacts in one run trains once. The cache is
process-local; it does not survive restarts (acceptable at v0.1 scale).

**D11 — Image dimensions parsed from raw PNG/JPEG headers.**
`rungs/deterministic.py` — a ~30-line struct parser instead of a Pillow
dependency. Keep the dependency footprint minimal; add Pillow only when a
rung genuinely needs pixels (saliency, v0.2).

**D12 — API jobs are in-process.**
`api.py` uses FastAPI `BackgroundTasks` + a module-level dict. Documented
upgrade: durable queue + webhooks. Don't add infrastructure before the need
is real ("no premature infrastructure").

## Measured results (synthetic world, seed 7, keyless)

- Performance predictor calibration: **Spearman r = 0.92** (n=132→144).
- Judge ensemble (NullLLM heuristic): **Spearman r = 0.57**.
- Funnel fused ranking vs held-out true CTR: **Spearman 0.73** over 12
  survivors.
- All flawed/violating variants eliminated at the gate with exact evidence.
- Full suite: **45 tests pass, ~2s**, entirely offline/keyless.

Use these as regression baselines: if a change drops the synthetic-world
numbers materially, the change is wrong or the world got harder — find out
which before merging.

## Gotchas / sharp edges for future work

- **Rebuild the `FunnelEngine` after ingesting outcomes** if you want rungs to
  see fresh calibration records in their validity statements (the engine
  itself reads weights live via the harness, but the demo re-instantiates for
  clarity). See `cli.py::demo`.
- The judge's anchors come from ground-truth records with `text` present and
  the target metric in `outcomes`; a set without inline text silently reduces
  the judge to `judge_skipped`.
- `spearmanr` on constant arrays is NaN — the harness refuses degenerate
  cells (`recalibrate` returns None). Keep that guard.
- Synthetic-world ads sometimes contain "miracle" (spam component) and get
  gate-eliminated before scoring — that's why calibration n (132) < corpus
  size (200). Expected behavior, not a bug.
- The `.gitignore` excludes `*.db` and report HTML; never commit runtime
  artifacts.

## Decision log (append below)

<!-- Template:
### YYYY-MM-DD — short title
**Decision:** what was decided.
**Why:** the reasoning and alternatives rejected.
**Impact:** files/behaviors affected.
-->

### 2026-07-08 — D13: Dashboard SPA from the Claude Design handoff
**Decision:** Implemented the 4-view design (`docs/creative-gate-system-design/`)
as ONE self-contained vanilla-JS file (`src/creativegate/report/dashboard.html`)
served by FastAPI at `GET /`. No React/build toolchain.
**Why:** the codebase has zero frontend infrastructure and the charter says
"one clean report page + API is the product"; a bundler would be premature
infrastructure for ~900 lines of UI. Design fidelity kept (tokens, layout,
interactions), but every number is fetched live — no mocked data ever renders.
**Design→backend mapping decisions (deviations from the mock, all deliberate):**
- PASS/WARN/FAIL box: FAIL = eliminated; WARN = directional-only fusion or
  HUMAN_REVIEW flag or no score; PASS = survived with calibrated fusion.
- "Judge dimension" bars (Composition etc.) → per-anchor win-rates from the
  judge's real pairwise comparisons (our judge is pairwise-only per D4).
- Saliency heatmap card → honest artifact preview labeled "saliency · planned
  v0.2". Fake heatmaps would violate rules.md §6.
- "Spend calibration" $10→$10k chart → rung self-trust chart (Spearman per
  recalibration event from the audit trail) + weight table. We do not and
  will not track spend (out of scope).
- Marketing-home proof stats ("1.2M assets gated", "Gemini Flash") → live
  numbers from /verdicts and /calibration; real tech list.
- Added two cards the design lacked: validity statements and cheapest-next-test
  (the product's money features).
- Dropzone accepts .txt only (video = v1.0; image upload API doesn't exist yet).
**Backend additions:** `Verdict.runtime_ms` (schema 0.1.0→0.1.1, optional,
display-only, never fused); repo `artifacts` table + `list_verdicts` +
`all_calibrations`; endpoints `GET /` (SPA), `GET /verdicts`,
`GET /artifact/{id}`, `GET /calibration` (grouped audit trail).
**Impact:** api.py, cli.py (saves artifacts), schemas.py, storage/repo.py,
engine/funnel.py, report/dashboard.html, tests (46 now). Verified live against
the demo db: ingest→evaluate→dashboard round-trip, calibration chart from the
real audit trail, zero console errors.
