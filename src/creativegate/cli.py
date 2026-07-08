"""CreativeGate CLI.

Design rationale: the CLI is the fastest path to the wind tunnel. `demo`
runs the full product narrative end-to-end: generate a synthetic world,
calibrate, funnel 20 variants, predict the held-out ranking, reveal true
outcomes, and show the system updating how much it trusts itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from scipy import stats

from .calibration import CalibrationHarness, SyntheticWorld
from .engine import FunnelEngine
from .profiles import default_profile, load_profile
from .report import render_batch_report, render_verdict_report
from .schemas import Artifact, GroundTruthRecord, Modality
from .storage import Repository

app = typer.Typer(help="CreativeGate: evaluate creative artifacts before you spend.")


def _setup(db: str, profile_path: str | None, seed: int):
    profile = load_profile(profile_path) if profile_path else default_profile(seed=seed)
    repo = Repository(db)
    harness = CalibrationHarness(repo)
    gt = repo.get_ground_truth_set(profile.ground_truth_set)
    return profile, repo, harness, gt


@app.command()
def evaluate(
    text: str = typer.Option(None, help="Creative text to evaluate."),
    file: Path = typer.Option(None, help="File containing the creative (txt)."),
    artifact_id: str = typer.Option("cli-artifact", help="Identifier for the artifact."),
    segment: str = typer.Option("default"),
    profile: str = typer.Option(None, help="Path to a profile YAML/JSON."),
    db: str = typer.Option("creativegate.db"),
    report: Path = typer.Option(None, help="Write an HTML verdict report here."),
    seed: int = typer.Option(7),
):
    """Run one artifact through the funnel and print the verdict."""
    if text is None and file is None:
        raise typer.BadParameter("Provide --text or --file.")
    content = text if text is not None else file.read_text()

    prof, repo, harness, gt = _setup(db, profile, seed)
    if gt is None:
        typer.echo("No ground-truth set in the database; run `creativegate seed-synthetic` first "
                   "or the predictor/judge will refuse and only the gate will run.")
    engine = FunnelEngine(prof, ground_truth=gt, harness=harness)
    artifact = Artifact(id=artifact_id, modality=Modality.TEXT, text=content, segment=segment)
    verdict = engine.evaluate(artifact)
    repo.save_verdict(verdict)

    typer.echo(json.dumps(json.loads(verdict.model_dump_json()), indent=2))
    if report:
        report.write_text(render_verdict_report(verdict))
        typer.echo(f"\nHTML report: {report}")


@app.command()
def seed_synthetic(
    n: int = typer.Option(200, help="Number of synthetic ground-truth records."),
    db: str = typer.Option("creativegate.db"),
    seed: int = typer.Option(7),
):
    """Create and store the synthetic starter ground-truth set, then calibrate."""
    world = SyntheticWorld(seed=seed)
    gt = world.generate_set(n)
    repo = Repository(db)
    repo.save_ground_truth_set(gt)

    # Bootstrap calibration: score the corpus with each scoring rung, then
    # ingest the known outcomes so the harness can measure each rung's worth.
    harness = CalibrationHarness(repo)
    prof = default_profile(seed=seed)
    engine = FunnelEngine(prof, ground_truth=gt, harness=harness)
    for r in gt.records:
        artifact = Artifact(id=r.artifact_ref, modality=r.modality, text=r.text, segment=r.segment)
        engine.evaluate(artifact)
    updated = harness.ingest_outcomes(gt.records)
    typer.echo(f"Stored '{gt.name}' with {n} records in {db}.")
    for rec in updated:
        typer.echo(f"  calibrated {rec.rung}: Spearman r={rec.spearman:.2f} (n={rec.n})")


@app.command()
def calibration(
    rung: str = typer.Argument(..., help="Rung name, e.g. performance_predictor."),
    db: str = typer.Option("creativegate.db"),
):
    """Print the validity report for a rung."""
    repo = Repository(db)
    harness = CalibrationHarness(repo)
    report = harness.report(rung)
    typer.echo(report.summary)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    db: str = typer.Option("creativegate.db"),
):
    """Start the CreativeGate API."""
    import os
    import uvicorn
    os.environ["CREATIVEGATE_DB"] = db
    uvicorn.run("creativegate.api:app", host=host, port=port)


@app.command()
def demo(
    out: Path = typer.Option(Path("demo_report.html"), help="Output HTML report."),
    db: str = typer.Option("demo_creativegate.db"),
    seed: int = typer.Option(7),
):
    """The full product narrative on a synthetic world with known physics.

    1. Generate a 200-ad synthetic world; hold out 20 variants (plus inject
       deliberately flawed ones).
    2. Calibrate every rung on the 180 training ads.
    3. Funnel the 20+flawed variants: eliminate violators with evidence,
       rank survivors with confidence bands.
    4. Score the funnel's ranking against the held-out TRUE outcomes.
    5. Reveal the outcomes to the system and show the calibration update —
       the system learning how much to trust itself.
    """
    Path(db).unlink(missing_ok=True)
    world = SyntheticWorld(seed=seed)
    full = world.generate_set(220)
    train_records = full.records[:200]
    holdout = full.records[200:220]

    gt = full.model_copy(update={"records": train_records})
    repo = Repository(db)
    repo.save_ground_truth_set(gt)
    harness = CalibrationHarness(repo)
    prof = default_profile(seed=seed)

    typer.echo("=== 1. Calibrating rungs on 200 synthetic ads with known outcomes ===")
    engine = FunnelEngine(prof, ground_truth=gt, harness=harness)
    for r in train_records:
        engine.evaluate(Artifact(id=r.artifact_ref, modality=r.modality, text=r.text, segment=r.segment))
    for rec in harness.ingest_outcomes(train_records):
        typer.echo(f"  {rec.rung}: Spearman r={rec.spearman:.2f} vs ctr (n={rec.n})")

    typer.echo("\n=== 2. Funnel: 20 held-out variants + 3 deliberately flawed ones ===")
    flawed = [
        Artifact(id="flawed-banned", modality=Modality.TEXT, text="Miracle skincare, guaranteed results! Buy now."),
        Artifact(id="flawed-no-cta", modality=Modality.TEXT, text="Our standing desks exist and they are made of wood."),
        Artifact(id="flawed-too-short", modality=Modality.TEXT, text="Buy now."),
    ]
    candidates = [
        Artifact(id=r.artifact_ref, modality=r.modality, text=r.text, segment=r.segment)
        for r in holdout
    ] + flawed

    # Rebuild the engine so rungs see the just-written calibration records.
    engine = FunnelEngine(prof, ground_truth=gt, harness=harness)
    verdicts = engine.evaluate_batch(candidates)
    eliminated = [v for v in verdicts if v.eliminated]
    survivors = [v for v in verdicts if not v.eliminated and v.score is not None]
    for v in eliminated:
        typer.echo(f"  ELIMINATED {v.artifact_id} at {v.eliminated_by}: {v.validity_summary}")
    typer.echo(f"  {len(survivors)} survivors ranked with confidence bands.")

    typer.echo("\n=== 3. Did the funnel predict the real ranking? (held-out truth) ===")
    truth = {r.artifact_ref: r.outcomes["ctr"] for r in holdout}
    pairs = [(v.score, truth[v.artifact_id]) for v in survivors if v.artifact_id in truth]
    rho = float(stats.spearmanr([p for p, _ in pairs], [t for _, t in pairs]).statistic)
    typer.echo(f"  Spearman(funnel score, TRUE held-out CTR) = {rho:.2f} over {len(pairs)} artifacts")

    top3 = sorted(survivors, key=lambda v: v.score, reverse=True)[:3]
    typer.echo("\n=== 4. Cheapest next test for the top 3 ===")
    for v in top3:
        typer.echo(f"  {v.artifact_id} (score {v.score:.2f}, band [{v.band[0]:.2f}-{v.band[1]:.2f}]): "
                   f"{v.next_test.kind} — {v.next_test.rationale[:110]}...")

    typer.echo("\n=== 5. Revealing held-out outcomes: the system updates its self-trust ===")
    before = {r: harness.lookup(r, "default", "text") for r in ("performance_predictor", "judge_ensemble")}
    updated = harness.ingest_outcomes(holdout)
    for rec in updated:
        prev = before.get(rec.rung)
        prev_s = f"{prev.spearman:.2f}" if prev else "n/a"
        drift = "  [DRIFT ALARM]" if rec.drift_detected else ""
        typer.echo(f"  {rec.rung}: Spearman {prev_s} -> {rec.spearman:.2f} (n={rec.n}){drift}")

    note = (
        f"Held-out validation: Spearman(funnel score, true CTR) = {rho:.2f} over {len(pairs)} "
        f"unseen artifacts. After the reveal, rung calibrations were updated with n+20 outcomes "
        f"(see CLI output) — the system re-measured how much to trust itself."
    )
    out.write_text(render_batch_report(verdicts, title="synthetic-world demo", note=note))
    for v in verdicts:
        repo.save_verdict(v)
    typer.echo(f"\nHTML report: {out}")


if __name__ == "__main__":
    app()
