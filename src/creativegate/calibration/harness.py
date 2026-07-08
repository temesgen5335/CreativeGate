"""The calibration harness.

Design rationale: this is the honesty engine and the product's spine. It
answers one question per (rung, segment, modality): *how well do this rung's
predictions actually correlate with real outcomes?* — and it is the ONLY
source of fusion weight and validity claims in the system.

Mechanics:
- ``record_prediction`` stores what a rung predicted for an artifact.
- ``ingest_outcomes`` stores what reality said.
- ``recalibrate`` joins the two, computes Spearman + Pearson per
  (rung, segment, modality), compares against the previous window, and
  raises a drift flag when correlation decays materially.

Every recalibration appends to an audit trail; nothing is silently
overwritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from scipy import stats

from ..schemas import CalibrationRecord, CalibrationReport, utcnow
from ..storage.repo import Repository

MIN_SAMPLES = 5
DRIFT_DECAY_THRESHOLD = 0.15  # absolute Spearman drop that raises a drift alarm


class CalibrationHarness:
    def __init__(self, repo: Repository):
        self.repo = repo

    # -- write paths --------------------------------------------------------

    def record_prediction(self, rung: str, artifact_ref: str, segment: str,
                          modality: str, metric: str, predicted: float,
                          verdict_id: Optional[str] = None) -> None:
        self.repo.save_prediction(rung, artifact_ref, segment, modality, metric,
                                  predicted, verdict_id)

    def ingest_outcomes(self, records: list) -> list[CalibrationRecord]:
        """Store ground-truth outcomes, then recalibrate every affected
        (rung, segment, modality) cell. Returns the updated records."""
        for r in records:
            self.repo.save_outcome(r)
        cells = self.repo.affected_cells([r.artifact_ref for r in records])
        updated = []
        for rung, segment, modality, metric in cells:
            rec = self.recalibrate(rung, segment, modality, metric)
            if rec is not None:
                updated.append(rec)
        return updated

    # -- calibration math ----------------------------------------------------

    def recalibrate(self, rung: str, segment: str, modality: str, metric: str) -> Optional[CalibrationRecord]:
        pairs = self.repo.prediction_outcome_pairs(rung, segment, modality, metric)
        if len(pairs) < MIN_SAMPLES:
            return None
        preds = [p for p, _ in pairs]
        outs = [o for _, o in pairs]
        if len(set(preds)) < 2 or len(set(outs)) < 2:
            return None  # degenerate: correlation undefined
        spearman = float(stats.spearmanr(preds, outs).statistic)
        pearson = float(stats.pearsonr(preds, outs).statistic)

        previous = self.repo.latest_calibration(rung, segment, modality)
        drift = bool(
            previous is not None
            and previous.spearman - spearman > DRIFT_DECAY_THRESHOLD
        )
        record = CalibrationRecord(
            rung=rung, segment=segment, modality=modality, metric=metric,
            spearman=spearman, pearson=pearson, n=len(pairs),
            previous_spearman=previous.spearman if previous else None,
            drift_detected=drift,
            notes=(
                f"Recalibrated from {len(pairs)} prediction/outcome pairs."
                + (f" DRIFT: Spearman fell {previous.spearman:.2f} -> {spearman:.2f}; "
                   "fusion weight reduced accordingly." if drift else "")
            ),
        )
        self.repo.save_calibration(record)  # appends; audit trail preserved
        return record

    # -- read paths ----------------------------------------------------------

    def lookup(self, rung: str, segment: str, modality: str) -> Optional[CalibrationRecord]:
        return self.repo.latest_calibration(rung, segment, modality)

    def fusion_weight(self, rung: str, segment: str, modality: str, min_r: float = 0.1) -> float:
        """Weight = measured Spearman, floored at 0, zero when uncalibrated,
        below min_r, or too few samples. An uncalibrated rung can therefore
        never carry weight — safety rail §9.6."""
        rec = self.lookup(rung, segment, modality)
        if rec is None or rec.n < MIN_SAMPLES:
            return 0.0
        r = rec.spearman
        if rec.drift_detected:
            r *= 0.5  # decayed judges get their weight cut, with the audit note above
        return r if r >= min_r else 0.0

    def report(self, rung: str) -> CalibrationReport:
        records = self.repo.calibrations_for_rung(rung)
        latest_by_cell: dict[tuple, CalibrationRecord] = {}
        for r in sorted(records, key=lambda r: r.updated_at):
            latest_by_cell[(r.segment, r.modality)] = r
        latest = list(latest_by_cell.values())
        if not latest:
            summary = f"'{rung}' is unvalidated everywhere: no calibration records. Scores are directional only."
        else:
            parts = [
                f"segment='{r.segment}'/modality='{r.modality}': Spearman r={r.spearman:.2f} "
                f"vs {r.metric} (n={r.n}{', DRIFT' if r.drift_detected else ''})"
                for r in latest
            ]
            summary = f"'{rung}' validated for " + "; ".join(parts) + ". Unvalidated elsewhere."
        return CalibrationReport(rung=rung, records=latest, summary=summary)
