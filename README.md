# CreativeGate

**A simulation-first evaluation funnel for digital creative artifacts.**
Evaluate before you spend — and make every cheap evaluator earn its trust by
continuous calibration against the expensive ones.

Given a creative artifact (ad copy, caption, image, …) and a ground-truth set
of artifacts with known real-world outcomes, CreativeGate answers:

> *How likely is this artifact to work on real end-users — with what
> confidence, according to which validated evaluators — and what is the
> cheapest next test that would raise that confidence?*

The metaphor is a **wind tunnel**: aircraft are tested in instrumented rigs
long before a pilot flies one. Digital creative mostly skips the wind tunnel
and goes from generation straight to spend. CreativeGate is the wind tunnel —
plus the discipline that keeps a wind tunnel honest: every simulated
measurement is continuously calibrated against real-world outcomes.

## The funnel

```
                         artifacts (cheap to produce, expensive to test live)
                              │
             ┌────────────────▼────────────────┐
   FREE      │ 1. Deterministic Gate           │  banned claims, required CTA,
             │    pass/fail + evidence         │  structural specs, brand rules
             └────────────────┬────────────────┘  * catches violations,
                              │ survivors           never measures quality
             ┌────────────────▼────────────────┐
   CHEAP     │ 2. Performance Predictor        │  GBM ensemble over engineered
             │    predicted CTR ± uncertainty  │  + embedding features, trained
             └────────────────┬────────────────┘  on the ground-truth set
                              │ survivors
             ┌────────────────▼────────────────┐
   MODERATE  │ 3. Calibrated Judge Ensemble    │  pairwise A/B vs known-outcome
             │    outcome-weighted win-rate    │  anchors, temp 0, N passes,
             └────────────────┬────────────────┘  variance reported
                              │
             ┌────────────────▼────────────────┐
             │ Calibration-weighted fusion     │  weight = MEASURED Spearman vs
             │ score ± confidence band         │  real outcomes; uncalibrated
             │ + evidence ledger               │  rungs get flags, never weight
             │ + cheapest-next-test            │
             └────────────────┬────────────────┘
                              │ outcomes flow back
             ┌────────────────▼────────────────┐
             │ Calibration harness             │  re-scores every cheap rung's
             │ (the honesty engine)            │  predictions against reality,
             └─────────────────────────────────┘  cuts drifting weights, audits
```

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"

# The full product narrative on a synthetic world with known physics:
# calibrate → funnel 23 variants → validate ranking on held-out truth →
# reveal outcomes → watch the system update its own self-trust.
uv run creativegate demo

# Seed a working database and evaluate your own copy:
uv run creativegate seed-synthetic
uv run creativegate evaluate --text "Meet your new favorite running shoes. Free shipping. Shop now." --report verdict.html

# Validity report for a rung — the system volunteers its own limits:
uv run creativegate calibration performance_predictor

# API + dashboard:
uv run creativegate serve   # opens the live dashboard at http://127.0.0.1:8000/
                            # (ingest, verdict telemetry, calibration harness)
                            # plus POST /evaluate, GET /verdict/{id}, POST /ground-truth, ...
```

**Production posture** (all optional, off by default): set
`CREATIVEGATE_API_TOKEN` to require a bearer token on mutating endpoints
(open the dashboard once as `/?token=…`); `POST /artifacts` uploads
.txt/.png/.jpg payloads for evaluation by reference; evaluation jobs are
durable in the database (a restart marks in-flight jobs `interrupted`, and
`webhook_url` on `POST /evaluate` notifies on completion); trained predictor
models persist in `.creativegate_cache/` so restarts don't retrain; the
dashboard live-polls, so runs submitted by any client appear in every open
tab. `CREATIVEGATE_CORS_ORIGINS` enables cross-origin API use.

**Zero keys required.** With no LLM API key the judge uses a deterministic
heuristic comparator and the predictor uses TF-IDF fallback embeddings; both
are clearly labeled `degraded` fidelity in every verdict. Set
`OPENAI_API_KEY` (or `CREATIVEGATE_LLM_API_KEY` / `CREATIVEGATE_LLM_BASE_URL`
for any OpenAI-compatible endpoint) to upgrade the judge in place. Models are
enhancers, never dependencies.

## What a verdict contains

- **Fused score with a confidence band** — never a bare point score. Band
  width reflects rung disagreement, calibration weakness, and coverage.
- **Evidence ledger** — every check, comparison and prediction that produced
  the verdict, with the exact reason for any elimination.
- **Validity statements** — per rung: *"Validated for segment='default',
  modality='text': Spearman r=0.62 vs ctr (n=200)"* or *"Unvalidated —
  directional only."* The system volunteers its own limits.
- **Cheapest-next-test recommendation** — what is limiting confidence and the
  cheapest way to fix it (human pretest, micro-flight, sequential A/B).
- **Reproducibility stamp** — config hash, seed, rung/prompt versions; any
  verdict is replayable and any diff attributable.

## The calibration harness (the differentiator)

Every scoring rung's prediction is recorded. When real outcomes arrive
(`POST /ground-truth`), the harness joins predictions to outcomes, recomputes
Spearman/Pearson per (rung, segment, modality), appends to an audit trail,
and raises a **drift alarm** when a rung's correlation decays — the drifting
rung's fusion weight is cut automatically. A funnel without this loop becomes
confident noise within a quarter; this loop is the product.

The harness is itself tested against a **synthetic world** — a generative
model of ad outcomes with known physics — so calibration logic is verified
against a ground truth we control (`tests/test_synthetic_world.py`).

## Safety rails (encoded as the test suite's spine)

- An **uncalibrated rung can never carry fusion weight** — it contributes
  evidence and flags only.
- A rung can **never report validity it doesn't have** — validity is stamped
  by the framework from calibration records, not self-asserted.
- **Known-good anchors can never be silently buried**: scoring a proven
  converter below the profile floor raises `HUMAN_REVIEW_REQUIRED` instead of
  auto-rejecting.
- Deterministic gates have **zero variance**; whole verdicts are reproducible
  given the same seed and config hash.

## What this is not

- **Not an ad server and not a spend manager.** CreativeGate plans live tests
  (bandit priors, sequential designs, micro-flights — v0.3); it never serves
  traffic or moves money.
- **Not a guarantee.** A funnel score is a calibrated estimate with a stated
  band, valid only for segments/modalities with calibration records. Where it
  is unvalidated it says "directional only" — believe that label.
- **Not a replacement for live testing.** It is the filter that decides what
  *deserves* live testing, and it feeds on live outcomes to stay honest.
- **Not (yet) multimodal.** v0.1 evaluates text creatives end-to-end; the
  deterministic gate additionally checks image structure (aspect ratio,
  dimensions, file size). Saliency, video, personas, and OPE are later rungs.

## Architecture

```
src/creativegate/
  schemas.py           # the stable contract: Artifact, RungResult, Verdict, ...
  features.py          # shared engineered text features (versioned)
  profiles.py          # declarative funnel definitions (YAML/JSON)
  providers/           # LLM + embedding slots with keyless degradation
  rungs/               # the plugin interface + the three v0.1 rungs
  engine/              # funnel execution, calibration-weighted fusion, next-test
  calibration/         # the harness + the synthetic world
  storage/             # SQLite behind a repository interface (Postgres upgrade path)
  report/              # the honest HTML verdict report
  api.py               # FastAPI surface
  cli.py               # CLI incl. the end-to-end demo
```

Every rung implements one interface (`Rung.evaluate(artifact, ctx) ->
RungResult`), so custom evaluators plug in without core changes. New rungs
ship disabled-by-default; promotion requires the harness's evidence.

## Roadmap

- **v0.2** — MCP server; attention/saliency rung (image); event-driven
  recalibration; verdict replay.
- **v0.3** — Live-Test Planner (bandit specs with funnel priors, sequential
  designs with SRM gates, micro-flight designs); OPE rung with propensity
  validation; synthetic persona panel with "directional-only until
  calibrated" enforcement.
- **v1.0** — video; proxy-metric ladder; multi-tenant profiles; Postgres.
