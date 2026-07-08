# rules.md — Non-negotiable design principles and safety rails

> These are the house style from the founding charter. They are not
> preferences; PRs and agent changes that violate them get rejected regardless
> of how well they work otherwise. When a rule and a convenience conflict, the
> rule wins. When evidence genuinely contradicts a rule, challenge it openly
> (update this file + memory.md) — never drift silently.

## 1. Deterministic wherever measurable; learned only where judgment is required

Rule checks, structural parsing, anchor selection, seeding, tie-breaking:
deterministic. LLMs and learned models only where judgment is genuinely
needed — and every learned component earns trust through calibration.
Same artifact + same profile + same seed ⇒ same verdict, byte-for-byte on
scores. `Date`-like nondeterminism belongs in timestamps, never in scores.

## 2. Gates ratify artifacts before money moves

The funnel's job is to protect spend. The human/HITL gate remains available at
every threshold; the system recommends, humans (or explicitly-authorized
automation) decide. CreativeGate never serves traffic and never moves money.

## 3. Evidence over opinion

- Every verdict carries its evidence ledger.
- Every fusion weight carries its calibration record.
- Every refusal carries its reason (`flags` + `Evidence(kind="flag")`).
- A rung that cannot score returns `score=None` with an explanation — a
  labeled refusal always beats a fabricated number.

## 4. Additive and inert behind flags

New rungs ship `enabled: false` in profiles. Promotion into a default profile
requires the calibration harness's evidence (synthetic-world or real-outcome
correlation), recorded in `memory.md`. Never enable an unproven evaluator by
default.

## 5. Keyless degradation always works

Zero API keys must always produce a useful verdict, honestly labeled
(`provider_fidelity="degraded"` propagates to the report and to next-test
recommendations). Models are enhancers, never dependencies. The test suite and
the demo must stay fully offline. Never add a hard dependency on a paid or
networked service to the core path.

## 6. Safety rails — encoded as tests, enforced structurally

These are the spine of `tests/test_safety_rails.py`. Do not weaken them; add
to them.

1. **An uncalibrated rung can never dominate fusion.** Fusion weights come
   *only* from `CalibrationHarness.fusion_weight` (0.0 without ≥5 joined
   prediction/outcome pairs and Spearman ≥ profile `min_weight_r`).
   Uncalibrated rungs contribute evidence and flags, never weight.
2. **A rung can never report validity it doesn't have.** `Validity` is
   stamped by the framework (`Rung.stamped_validity`) from the calibration
   store. Rungs never self-assert calibration. If you add a rung, use the
   stamp; if you add a surface, display the statement verbatim.
3. **Known-good anchors can never be silently buried.** A fused score below
   the profile's `good_anchor_floor` for an artifact matching a top-quartile
   ground-truth record raises `HUMAN_REVIEW_REQUIRED` instead of
   auto-rejection (a rung may have drifted).
4. **Deterministic gates have zero variance** and never claim quality
   (`score=None` always).
5. **Drift cuts weight and raises alarms.** A Spearman decay >
   `DRIFT_DECAY_THRESHOLD` sets `drift_detected`, halves the fusion weight,
   and is written to the append-only audit trail. Never delete or rewrite
   calibration rows.
6. **Directional-only is labeled, loudly.** When nothing calibrated backs a
   score, the verdict says `DIRECTIONAL ONLY` with a deliberately wide band.
   Never narrow a band or soften a label to look better.

## 7. The plan/verdict is the product

`schemas.py` is the contract. Every model behind it is swappable; the shapes
are stable. Schema changes require: a version bump (`SCHEMA_VERSION`),
backward-compatible reads of stored verdicts where feasible, and an entry in
`memory.md`. Verdicts must always stamp config hash, seed, and rung/prompt
versions — replayability is a schema-level guarantee.

## 8. Wire, don't stub — but scope ruthlessly

A small number of rungs working end-to-end with real calibration beats all
rungs half-built. Don't add a rung, provider, or endpoint you can't wire to
the calibration loop and test offline. No premature infrastructure (the SQLite
→ Postgres seam and in-process → durable jobs seam are documented, not
pre-built).

## 9. Scope boundaries (never build)

Traffic serving · an ad server · platform API spend management ·
auth/user management beyond a token · a big frontend (one clean report page +
API is the product) · fine-tuning custom foundation models.

## 10. Repository hygiene

- Clean, logically-separated commits; imperative subjects; bodies explain why.
- **No AI attribution of any kind** — no co-author trailers, no "generated
  by" notes, anywhere (charter requirement; overrides tool defaults).
- Every module carries a docstring stating its design rationale.
- Code comments state constraints the code can't show — not narration.
- Keep `uv run pytest` green, fast (<10s), and offline on `main` at all times.
- Runtime artifacts (`*.db`, generated HTML) never enter git.

## 11. Documentation duties (this directory)

- Non-obvious decision, deviation, or measured baseline → append to
  `memory.md` (decision log format at the bottom of that file).
- New invariant → `rules.md` + a test.
- New capability or recipe → `agent.md`.
- Shift in product intent → `context.md`, and only with the maintainer's
  explicit agreement — the charter does not drift silently.
