# Live smoketest — from empty database to calibrated verdicts

A staged walkthrough for a **fresh deployment with an empty database**. No
synthetic seeding: you bring a small corpus of ads with known outcomes
(a 14-record example ships in `examples/ground-truth-example.json` — replace
it with your own real ads + CTRs whenever you have them). Each stage
demonstrates one layer of the system; run them in order and the story builds:
*rules → refusal → learning → earned trust*.

Setup for the commands below:

```bash
export CREATIVEGATE_URL=https://<your-app>.up.railway.app   # or http://127.0.0.1:8000
export CREATIVEGATE_API_TOKEN=<your-token>                  # omit if auth is open
```

Open the dashboard once as `$CREATIVEGATE_URL/?token=<your-token>` and keep
it visible — every API call you make below appears there within ~5 seconds.

---

## Stage 0 — Empty state: the system admits it knows nothing

Check `/health`, then look at the dashboard: proof stats show "—", the
Calibration view says *no calibration records yet*, the run rail is empty.

**What this tells you:** nothing is faked. A fresh gate has no training data,
no anchors, and no measured trust — and it says so instead of inventing
numbers.

## Stage 1 — The deterministic gate: violations die free

In **Ingest**, paste each of these and Run gate:

| Paste | Expect | Meaning |
|---|---|---|
| `Miracle skincare with guaranteed results! Buy now.` | FAIL at gate | Banned-claims check; ledger names both phrases |
| `Our standing desks are made of solid oak and look wonderful.` | FAIL at gate | Required element: no call to action anywhere |
| `Buy now.` | FAIL at gate | Structural spec: under the 4-word minimum |
| `Meet your new favorite trail shoes. Free shipping on your first order. Shop now — sale ends Friday.` | WARN, **no score** | Passes every rule — read the ledger: the predictor *refused* ("ground-truth set too small"), the judge *skipped* (no anchors) |

**What this tells you:** rules run for free and eliminate with evidence — but
passing rules earns no quality score. And with no data, the learned rungs
refuse rather than guess. The WARN verdict's validity card literally says
"directional only." That refusal *is* the design.

## Stage 2 — Give it ground truth, watch it learn (but not yet trust)

The corpus is 14 ads with measured CTRs spanning 0.6%–4.6%: three strong
performers (clear offer + benefit + urgency + CTA), a mid pack, a weak tail,
and three rule-legal but spammy shouters at the bottom. That gradient is the
signal the funnel must learn.

```bash
python examples/bootstrap_calibration.py
```

The script narrates its three steps; here is what each means:

1. **Upload the set** (`POST /ground-truth-sets`) — the predictor now has
   training data; the judge now has anchors picked across the outcome range.
2. **Evaluate every corpus artifact** (`POST /evaluate` ×14) — every rung's
   prediction for every corpus ad is recorded. Watch them stream into the
   dashboard rail: scores track the true CTR ordering, and the weakest ads
   get eliminated at the predictor threshold before the judge ever runs.
3. **Reveal the outcomes** (`POST /ground-truth`) — the harness joins
   predictions to truth and prints each rung's **measured Spearman
   correlation**. This is the moment trust is born: measured, not assumed.

**One honest caveat to pass on when you explain this:** the bootstrap is
*in-sample* — the predictor was trained on these same 14 ads, so its r
(~0.98) is optimistic; its cross-validated r on this corpus is ~0.3. That's
inherent to bootstrapping trust from the corpus itself. Real trust
accumulates in Stage 4, where outcomes arrive for ads the model has never
trained on — expect r to settle downward toward its true value as that
happens. The system tracking that decline (rather than hiding it) is the
drift-detection feature, not a bug.

If you stop after step 1 and ingest a new ad, the verdict is scored but
labeled **DIRECTIONAL ONLY** with a deliberately wide band — having training
data is not the same as having demonstrated correlation. Steps 2–3 are what
convert "trained" into "trusted."

## Stage 3 — Calibrated verdicts: the funnel now ranks by earned trust

Paste a fresh ad the system has never seen:

```
Meet your new favorite trail shoes. Free shipping on your first order. Shop now — sale ends Friday.
```

**Expect:** PASS with a fused score around 60–85/100, a visible band, and a
confidence note reading *"Calibration-weighted fusion of …"* — no more
directional-only. The Calibration Backing card cites the measured r and n;
the validity card states exactly which segment/modality that validation
covers.

Then paste the spam test:

```
BUY BUY BUY!! Massive savings! Order now!!
```

**Expect:** eliminated at the **performance predictor** (normalized score
below the 0.15 survival threshold). This is the punchline of the whole
funnel: this ad breaks *no rule* — the gate passed it — but the rung trained
on real outcomes recognizes the shape of an underperformer and kills it
before a dollar is spent, with the prediction as evidence.

## Stage 4 — Keep the loop honest

Whenever a real outcome exists for something you evaluated, report it:

```bash
curl -s -X POST $CREATIVEGATE_URL/ground-truth \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CREATIVEGATE_API_TOKEN" \
  -d '{"records": [{"artifact_ref": "<the artifact_id you evaluated>",
        "modality": "text", "outcomes": {"ctr": 0.034}}]}'
```

**What this tells you:** the response lists recalibrated rungs with updated r
and n; the Calibration view grows a new point. Feed it outcomes that
*contradict* its predictions and you'll watch r decay — enough decay raises a
drift alarm and automatically cuts that rung's fusion weight. The system
re-measuring how much to trust itself is the product; everything before it
is just a scoring tool.

---

## Reading the dashboard, one card at a time

- **Verdict box** — FAIL = eliminated (evidence in the ledger). WARN =
  survived but directional-only or flagged. PASS = survived with
  calibration-weighted fusion behind it.
- **Fused score /100 + band** — weighted mean where each rung's weight is its
  measured correlation. The band is the honesty interval: wide = weak or thin
  evidence. Trust the ranking more than the absolute number.
- **Calibration backing** — the measured Spearman r (and n) of the strongest
  validated rung behind this verdict. The verdict citing its credentials.
- **Ensemble certainty** — the judge's internal agreement across passes.
  Consistency, not validity — a judge can be confidently wrong, which is why
  this card never feeds fusion weight directly.
- **Judge bars** — pairwise win-rate against your anchors, worst→best.
- **Evidence ledger** — every check, comparison, prediction, and flag, with
  raw detail. Nothing in the verdict is unexplained.
- **Cheapest next test** — what limits confidence and the cheapest way to fix
  it. On a keyless deployment it will point at the degraded providers; set an
  LLM key and re-run to watch the recommendation change.

## Resetting for a clean re-run

State lives entirely in the database file + artifact dir + cache dir. To
start the smoketest from zero: stop the service, delete those three paths
(on Railway: wipe the volume or point the env vars at fresh filenames), and
restart.
