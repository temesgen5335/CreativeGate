"""The synthetic world: a known generative model of creative outcomes.

Design rationale: the calibration harness must itself be testable, so we
ship a world where WE wrote the physics. Ad texts are generated from
templated components with known appeal coefficients; CTR is a logistic
function of those true features plus seeded noise. Because the true
outcome model is known, tests can assert that (a) the predictor recovers a
strong correlation, (b) the harness measures approximately the correlation
that analytically must exist, and (c) drift detection fires when the world's
physics are deliberately shifted.
"""

from __future__ import annotations

import numpy as np

from ..schemas import GroundTruthRecord, GroundTruthSet, Modality, OutcomeQuality

# The true physics: how much each latent component actually moves CTR.
TRUE_WEIGHTS = {
    "cta": 0.9,
    "urgency": 0.45,
    "benefit": 0.55,
    "spam": -1.1,
    "good_length": 0.35,
    "question": 0.15,
}
BASE_LOGIT = -3.6  # baseline CTR ~ 2.7%
NOISE_STD = 0.25   # logit-space outcome noise

_PRODUCTS = [
    "running shoes", "meal kits", "project software", "noise-canceling headphones",
    "language app", "standing desks", "skincare set", "budgeting app",
    "coffee subscription", "online course",
]
_HOOKS = [
    "Meet your new favorite {p}",
    "The {p} everyone is talking about",
    "Upgrade your day with {p}",
    "Finally, {p} that just work",
    "Your {p} search ends here",
]
_CTAS = ["Shop now", "Get started today", "Try it free", "Learn more", "Claim your offer"]
_URGENCY = ["Limited time only.", "Sale ends today.", "Don't miss out.", ""]
_BENEFITS = ["Save 30% on your first order.", "Free shipping included.", "Loved by 50,000 customers.", ""]
_SPAM = ["100% GUARANTEED!!", "MIRACLE results, act now!!", ""]


class SyntheticWorld:
    """Generates (text, true_features, ctr) triples from known physics."""

    def __init__(self, seed: int = 7, weights: dict[str, float] | None = None):
        self.seed = seed
        self.weights = dict(weights or TRUE_WEIGHTS)
        self.rng = np.random.RandomState(seed)

    def sample(self, i: int) -> tuple[str, dict[str, float], float]:
        rng = np.random.RandomState(self.seed * 100_003 + i)  # per-item determinism
        product = _PRODUCTS[rng.randint(len(_PRODUCTS))]
        hook = _HOOKS[rng.randint(len(_HOOKS))].format(p=product)

        has_cta = rng.rand() < 0.7
        urgency = _URGENCY[rng.randint(len(_URGENCY))]
        benefit = _BENEFITS[rng.randint(len(_BENEFITS))]
        spam = _SPAM[rng.randint(len(_SPAM))] if rng.rand() < 0.25 else ""
        question = rng.rand() < 0.2

        parts = [hook + ("?" if question else ".")]
        if benefit:
            parts.append(benefit)
        if urgency:
            parts.append(urgency)
        if spam:
            parts.append(spam)
        if has_cta:
            parts.append(_CTAS[rng.randint(len(_CTAS))] + ".")
        text = " ".join(parts)

        n_words = len(text.split())
        feats = {
            "cta": 1.0 if has_cta else 0.0,
            "urgency": 1.0 if urgency else 0.0,
            "benefit": 1.0 if benefit else 0.0,
            "spam": 1.0 if spam else 0.0,
            "good_length": 1.0 if 8 <= n_words <= 26 else 0.0,
            "question": 1.0 if question else 0.0,
        }
        logit = BASE_LOGIT + sum(self.weights[k] * v for k, v in feats.items())
        logit += rng.normal(0, NOISE_STD)
        ctr = float(1.0 / (1.0 + np.exp(-logit)))
        return text, feats, ctr

    def true_ctr_noiseless(self, feats: dict[str, float]) -> float:
        logit = BASE_LOGIT + sum(self.weights[k] * v for k, v in feats.items())
        return float(1.0 / (1.0 + np.exp(-logit)))

    def generate_set(self, n: int, name: str = "synthetic-starter",
                     segment: str = "default", start_index: int = 0) -> GroundTruthSet:
        records = []
        for i in range(start_index, start_index + n):
            text, feats, ctr = self.sample(i)
            records.append(GroundTruthRecord(
                artifact_ref=f"syn-{i:04d}",
                modality=Modality.TEXT,
                segment=segment,
                outcomes={"ctr": round(ctr, 5)},
                outcome_quality=OutcomeQuality.MEASURED,
                text=text,
                features=feats,
                is_anchor=True,
            ))
        return GroundTruthSet(name=name, target_metric="ctr", records=records)


def make_starter_set(n: int = 200, seed: int = 7) -> GroundTruthSet:
    """The synthetic starter GroundTruthSet the product ships with."""
    return SyntheticWorld(seed=seed).generate_set(n)
