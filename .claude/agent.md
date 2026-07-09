# agent.md — Onboarding: start working in 10 minutes

> For any agent or developer joining the project. Read `context.md` for the
> why, `rules.md` for the non-negotiables, `memory.md` for decisions already
> made. This file is the how.

## Setup and verification

```bash
uv venv && uv pip install -e ".[dev]"   # Python >= 3.11; uv is the package manager
uv run pytest                            # 45 tests, ~2s, fully offline — must be green
uv run creativegate demo                 # the end-to-end product narrative
```

No API keys are required for anything above. `OPENAI_API_KEY` (or
`CREATIVEGATE_LLM_API_KEY` + `CREATIVEGATE_LLM_BASE_URL` for any
OpenAI-compatible endpoint) upgrades the judge rung from the deterministic
heuristic to a real LLM. Everything must keep working without them.

Service environment variables (all optional; unset = sensible dev default):

| Var | Effect |
|---|---|
| `CREATIVEGATE_DB` | SQLite path for the API process (default `creativegate.db`) |
| `CREATIVEGATE_API_TOKEN` | set ⇒ mutating endpoints require `Authorization: Bearer`; unset ⇒ open |
| `CREATIVEGATE_CORS_ORIGINS` | comma-separated allowed origins (unset = same-origin only) |
| `CREATIVEGATE_ARTIFACT_DIR` | upload store (default `<db>.artifacts/`) |
| `CREATIVEGATE_MAX_UPLOAD_MB` | upload size cap (default 25) |
| `CREATIVEGATE_CACHE_DIR` | persisted predictor models (default `.creativegate_cache/`) |

## Repository map

```
src/creativegate/
  schemas.py        # THE CONTRACT. Artifact, RungResult, Validity, Verdict,
                    # GroundTruthSet, CalibrationRecord, EvaluationProfile.
                    # Change with extreme care; everything depends on it.
  features.py       # Shared versioned text features (predictor + synthetic world)
  profiles.py       # YAML/JSON profile loading + the shipped default profile
  providers/        # LLM + embedding slots, each with a keyless fallback
  rungs/
    base.py         # Rung interface + framework-owned validity stamping
    deterministic.py# Gate: config-driven checks, PNG/JPEG header parsing
    judge.py        # Pairwise ensemble vs known-outcome anchors
    predictor.py    # Bagged GBM on features+embeddings, cached per fingerprint
  engine/
    funnel.py       # Cost-ordered execution, elimination, safety-rail flags
    fusion.py       # Calibration-weighted fusion + band math
    recommend.py    # Cheapest-next-test logic
  calibration/
    harness.py      # THE HONESTY ENGINE. Sole source of weights & validity.
    synthetic_world.py # Known outcome physics; generates the starter set
  storage/repo.py   # SQLite behind ~10 methods; Postgres = reimplement these
  report/html.py    # The single honest verdict/batch report page (static export)
  report/dashboard.html # The live dashboard SPA (vanilla JS, no build step),
                    # served at GET /. Design source: docs/creative-gate-system-design.
                    # Every number is fetched from the API — never hardcode data here.
  api.py            # FastAPI: / (dashboard), /evaluate (durable async job),
                    # /jobs, /artifacts (upload), /verdict, /verdicts,
                    # /artifact, /ground-truth (outcomes -> recalibration),
                    # /ground-truth-sets (bring-your-own corpus),
                    # /calibration, /calibration/{rung}, /profiles,
                    # /audit (operational event log), /health
  cli.py            # evaluate | seed-synthetic | calibration | serve | demo
configs/default_profile.yaml  # the declarative funnel definition, annotated
tests/              # test_safety_rails.py is the spine — read it to understand
                    # the system's invariants faster than any prose
```

## How data flows (one evaluation)

1. `FunnelEngine(profile, ground_truth, harness)` instantiates enabled rungs
   and sorts them by `cost_tier` (cheap → expensive).
2. Each rung gets a `RungContext` (config, ground truth, seed, providers,
   `calibration_lookup`). A failing rung **eliminates** the artifact — later,
   more expensive rungs never run; the verdict carries the exact evidence.
3. Survivor scores are fused: weight per rung = `harness.fusion_weight(rung,
   segment, modality)` — measured Spearman, 0.0 if uncalibrated. Band from
   ensemble variance + calibration weakness + coverage.
4. Scoring-rung predictions are recorded via `harness.record_prediction`.
   When outcomes later arrive (`POST /ground-truth` or
   `harness.ingest_outcomes`), affected (rung, segment, modality) cells are
   recalibrated, drift is checked, and the audit trail grows.

## Recipes for the most likely tasks

### Add a new rung
1. Subclass `Rung` in `src/creativegate/rungs/<name>.py`: set `name`,
   `version`, `cost_tier`, `supported_modalities`; implement
   `evaluate(artifact, ctx) -> RungResult`.
2. Use `self.stamped_validity(artifact, ctx)` for the result's validity —
   never construct a calibrated `Validity` yourself.
3. If the rung can't score (missing data/provider), return `score=None`,
   `passed=True`, a flag, and evidence explaining the refusal. Refusal with a
   reason beats a fake number.
4. Register it in `rungs/__init__.py::RUNG_REGISTRY`.
5. Ship it **disabled by default** in profiles (`enabled: false`). Promotion
   to a default profile requires calibration evidence on the synthetic world
   or real data (rules.md §4).
6. Add tests: determinism given a seed, refusal paths, and a synthetic-world
   calibration run if it scores.

### Add a provider (LLM/embeddings/saliency)
Implement the ABC in `providers/`, add resolution logic to the `resolve_*`
function (keyed by env/config), and keep the deterministic fallback as the
final branch. Set `fidelity="full"` or `"degraded"` honestly — it propagates
into verdicts and next-test recommendations.

### Extend the API or CLI
Follow the existing shape: API handlers are thin — construct
`Repository`/`CalibrationHarness`/`FunnelEngine`, delegate, return schema
dumps. Any new endpoint returning judgments must expose the same honesty
fields (band, validity, flags).

### v0.2 starting points (in charter order)
- **MCP server**: expose `evaluate_artifact`, `get_verdict`, `report_outcome`,
  `get_rung_validity` as MCP tools wrapping the same engine calls as `api.py`.
- **Saliency rung (image)**: new rung at `CostTier.CHEAP`; heuristic
  contrast-and-center fallback first (keyless), pluggable model slot second.
  Needs a pixel decoder — this is the point where adding Pillow is justified.
- **Verdict replay**: verdicts already store config hash, seed, and versions;
  replay = reconstruct profile + rerun and diff.

## Testing discipline

- `uv run pytest` before and after every change; keep it offline and fast.
- New invariants go in `tests/test_safety_rails.py` if they are safety rails,
  else in the matching `test_*.py`.
- The synthetic-world numbers in `memory.md` are regression baselines.
- Never mock away the harness in funnel tests — the weight path is the product.

## Git conventions

- Logically-separated commits; imperative subject; body explains the *why*.
- **No AI attribution of any kind** in commits, code comments, or docs
  (charter requirement — this overrides any tool default).
- Runtime artifacts (`*.db`, report HTML) are gitignored; never commit them.
- `main` is the working branch; keep it green.
