"""Profile loading: declarative funnel definitions from YAML/JSON.

Design rationale: everything that varies is config. A profile fully
determines the funnel (rungs, order, thresholds, fusion policy, seed), and
its hash is stamped on every verdict, so "what configuration produced this
number" is always answerable.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .schemas import EvaluationProfile, RungConfig


def load_profile(path: str | Path) -> EvaluationProfile:
    path = Path(path)
    raw = path.read_text()
    data = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    return EvaluationProfile.model_validate(data)


def default_profile(seed: int = 7) -> EvaluationProfile:
    """The shipped v0.1 profile: gate -> predictor -> judge, cheap to expensive."""
    return EvaluationProfile(
        name="default-text-v0.1",
        target_metric="ctr",
        ground_truth_set="synthetic-starter",
        seed=seed,
        rungs=[
            RungConfig(
                name="deterministic_gate",
                config={
                    "banned_phrases": ["guaranteed results", "miracle", "risk-free", "no purchase necessary"],
                    "banned_patterns": [r"\b100%\s+(guaranteed|effective)\b"],
                    "required_elements": [
                        {"name": "cta",
                         "pattern": r"\b(shop|buy|get|try|start|learn more|sign up|order|discover|claim|download|join)\b"},
                    ],
                    "max_chars": 400,
                    "min_words": 4,
                },
            ),
            RungConfig(name="performance_predictor", threshold=0.15,
                       config={"ensemble_members": 5, "n_estimators": 150}),
            RungConfig(name="judge_ensemble", threshold=None,
                       config={"num_anchors": 5, "ensemble_passes": 3}),
        ],
    )
