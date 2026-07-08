# context.md — What CreativeGate is and why it exists

> Read this first. It is the problem statement, the vision, and the end-product
> purpose. `rules.md` holds the non-negotiables, `memory.md` holds the build
> history and decisions, `agent.md` tells you how to start working.

## The problem

Teams that produce creative at scale (human, automated, or agentic pipelines)
have three widespread evaluation options, and each fails a different way:

1. **Live A/B testing** is the ground truth but is expensive and slow: it burns
   real budget and real audience on losers, needs large samples per variant,
   and cannot keep pace with generation systems producing hundreds of variants
   per day. Testing everything live is economically impossible.
2. **LLM/agentic judges** are cheap and flexible but non-deterministic and
   model-dependent. An unvalidated judge is *confident noise* — nobody can say
   what a "78/100" means in conversions.
3. **Deterministic rule checks** are reliable but too strict and too shallow:
   they catch violations, not quality. A creative can pass every rule and
   still bore every human who sees it.

The missing insight: these are not competing alternatives. They are **rungs of
a funnel ordered by cost-per-evaluation and fidelity-to-reality**, and the
industry uses several more rungs in isolation that almost nobody composes into
one system (calibrated judge ensembles, learned performance predictors,
saliency models, persona panels, proxy ladders, off-policy evaluation,
sequential testing, bandits, micro-flights).

## The thesis

> **Evaluate before you spend — and make every cheap evaluator earn its trust
> by continuous calibration against the expensive ones.**

The metaphor is a **wind tunnel**: aircraft are tested in instrumented rigs
long before a pilot flies one. Digital creative mostly skips the wind tunnel
and goes from generation straight to spend. CreativeGate is the wind tunnel —
plus the discipline that keeps a wind tunnel honest: every simulated
measurement is continuously calibrated against real-world outcomes.

## The core question every verdict answers

> "How likely is this artifact to work on real end-users — with what
> confidence, according to which validated evaluators — and what is the
> cheapest next test that would raise that confidence?"

Note the three parts. A score alone is not a verdict. A verdict is:
**score ± band** + **evidence ledger** + **validity statements** (the system
volunteers its own limits) + **cheapest-next-test recommendation**.

## The two product surfaces

1. **The Funnel** (built, v0.1): a configurable pipeline of composable
   evaluation rungs any artifact runs through in seconds-to-minutes, producing
   a scored verdict with confidence bands and per-rung evidence.
2. **The Live-Test Planner** (v0.3, not yet built): given funnel survivors and
   budget/traffic constraints, recommends and configures the appropriate live
   protocol (bandit with funnel scores as priors, sequential A/B with SRM
   gates, micro-flight/geo-split, human pretest panel) and ingests results to
   close the calibration loop. CreativeGate **plans** live tests; it never
   serves traffic or moves money.

## Who the users are

- Creative/growth teams gating variants before spend.
- **Autonomous creative pipelines** (caption generators, DCO stacks, agent
  frameworks) that must gate their own outputs — they call `POST /evaluate`
  or (v0.2) the MCP tools. Agentic callers are first-class, not an
  afterthought.
- Adjacent prior art in the builder's ecosystem (a creative pipeline with a
  heuristic critic, a search-term auditor with the same "evaluate before you
  spend" thesis) are natural first integrators — but the system is standalone
  and generic; those integrations are proof points, not dependencies.

## The differentiator: the calibration harness

Every scoring rung's prediction is recorded. When real outcomes arrive, the
harness joins predictions to outcomes, recomputes Spearman/Pearson per
(rung, segment, modality), appends to an audit trail, and raises a drift alarm
when a rung's correlation decays — cutting that rung's fusion weight
automatically. **A funnel without this loop becomes confident noise within a
quarter; this loop is the product.** An honest "directional only" is a
feature, not an apology.

## The demo that proves the product

`uv run creativegate demo` — feed 20 held-out variants plus deliberately
flawed ones → the funnel eliminates violators with evidence, ranks survivors
with confidence bands, correctly predicts the ranking of held-out artifacts
whose real outcomes are known, admits where it's unvalidated, recommends the
cheapest live test for the top-3 — then, when the held-out outcomes are
revealed, **visibly updates its own rung calibrations**. That closing beat —
the system learning how much to trust itself — is the money shot.

## Roadmap

| Phase | Scope |
|---|---|
| **v0.1 (done)** | Schemas, funnel engine, 3 rungs (gate / judge / predictor), calibration harness + synthetic world, CLI, API, HTML verdict report |
| **v0.2** | MCP server; attention/saliency rung (image); event-driven recalibration; verdict replay |
| **v0.3** | Live-Test Planner (bandit specs with funnel priors, sequential designs with SRM gates, micro-flight designs); OPE rung with propensity validation; synthetic persona panel with directional-only enforcement |
| **v1.0** | Video modality; proxy-metric ladder; multi-tenant profiles; Postgres; hardening |

**Explicitly out of scope, never build:** traffic serving, an ad server,
platform spend management, auth beyond a token, a big frontend (one clean
report page + API is the product), fine-tuning foundation models.

The full founding charter (the complete original specification) is preserved
in `memory.md`'s references; when in doubt about intent, the charter's
language wins over any later shorthand.
