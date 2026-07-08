"""The cheapest-next-test recommendation.

Design rationale: every verdict ends with an action, not just a number.
Given what actually limits this verdict's confidence — an uncalibrated rung,
thin calibration samples, provider degradation, ensemble disagreement — pick
the cheapest live/paid step that would tighten it most. Cost figures are
config-supplied planning estimates, clearly labeled as such.
"""

from __future__ import annotations

from ..schemas import NextTest, RungResult

DEFAULT_COSTS = {
    "human_pretest": 400.0,     # ~200-response forced-choice panel
    "micro_flight": 1500.0,     # 3-day matched-geo pilot at ~2% budget
    "sequential_ab": 8000.0,    # full sequential test with early stopping
}


def recommend_next_test(results: list[RungResult], weights: dict[str, float],
                        band: tuple[float, float] | None,
                        costs: dict[str, float] | None = None) -> NextTest:
    costs = {**DEFAULT_COSTS, **(costs or {})}
    scored = [r for r in results if r.score is not None]
    uncalibrated = [r.rung for r in scored if weights.get(r.rung, 0.0) <= 0]
    degraded = [r.rung for r in scored if r.provider_fidelity == "degraded"]
    band_width = (band[1] - band[0]) if band else 1.0

    if scored and len(uncalibrated) == len(scored):
        return NextTest(
            kind="human_pretest",
            rationale=(
                "No scoring rung is calibrated for this segment/modality — the verdict is "
                "directional only. A small human pretest panel (forced-choice vs known anchors) "
                "is the cheapest way to create calibration data for every offline rung at once."
            ),
            estimated_cost_usd=costs["human_pretest"],
            expected_gain="Converts all offline rungs from directional to validated; expected band reduction >50%.",
        )
    if uncalibrated or degraded:
        limiters = sorted(set(uncalibrated + degraded))
        return NextTest(
            kind="human_pretest",
            rationale=(
                f"Confidence is limited by {', '.join(limiters)} "
                f"({'uncalibrated' if uncalibrated else 'running on degraded keyless providers'}). "
                "A human pretest panel would calibrate the weak rung(s) at panel cost, cheaper "
                "than any live traffic option."
            ),
            estimated_cost_usd=costs["human_pretest"],
            expected_gain="Adds calibration records for the weakest rungs; tightens future bands.",
        )
    if band_width > 0.30:
        return NextTest(
            kind="micro_flight",
            rationale=(
                f"All rungs are calibrated but the band is still wide ({band_width:.2f}). "
                "A small matched-geo micro-flight buys causal signal at ~2% of full-test cost "
                "and its outcomes feed the calibration loop."
            ),
            estimated_cost_usd=costs["micro_flight"],
            expected_gain="Real-outcome sample for this exact creative; typically halves the band.",
        )
    if band_width > 0.12:
        return NextTest(
            kind="sequential_ab",
            rationale=(
                "The funnel is confident enough to justify live traffic. A sequential test with "
                "always-valid early stopping (SRM-checked) will confirm at minimum spend."
            ),
            estimated_cost_usd=costs["sequential_ab"],
            expected_gain="Ground-truth confirmation; losers killed in days by early stopping.",
        )
    return NextTest(
        kind="none",
        rationale="Verdict is tight and fully calibration-backed; no cheaper test would materially change the decision.",
        estimated_cost_usd=0.0,
        expected_gain="",
    )
