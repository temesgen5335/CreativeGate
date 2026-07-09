"""Rung 3: the Performance Predictor.

Design rationale: "not rules, not a judge — a regression on reality." A
gradient-boosted ensemble trained on the ground-truth set maps engineered
features + embedding features to the target outcome. Uncertainty comes from
a bagged ensemble (std across members); honest self-assessment comes from
leave-out cross-validation Spearman, reported as evidence (fusion weight
still comes only from the calibration store).

The trained model is cached per (ground-truth-set, seed, config) fingerprint
so scoring many artifacts in one funnel run trains once.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold

from ..features import FEATURE_NAMES, FEATURE_VERSION, feature_vector
from ..providers import resolve_embeddings
from ..schemas import Artifact, CostTier, Evidence, GroundTruthSet, Modality, RungResult
from .base import Rung, RungContext

RUNG_VERSION = "0.1.0"
_MODEL_CACHE: dict[str, "_TrainedModel"] = {}


class _TrainedModel:
    def __init__(self, gt: GroundTruthSet, metric: str, seed: int, cfg: dict):
        texts = [r.text or "" for r in gt.records if r.text and metric in r.outcomes]
        y = np.array([r.outcomes[metric] for r in gt.records if r.text and metric in r.outcomes])
        if len(texts) < 10:
            raise ValueError(f"Ground-truth set too small to train predictor ({len(texts)} usable records; need >=10)")

        self.embedder = resolve_embeddings(cfg.get("embeddings"), seed=seed)
        self.embedder.fit(texts)
        X = self._features(texts)
        self.y_lo, self.y_hi = float(y.min()), float(y.max())

        n_members = int(cfg.get("ensemble_members", 5))
        rng = np.random.RandomState(seed)
        self.members: list[GradientBoostingRegressor] = []
        for m in range(n_members):
            idx = rng.choice(len(X), size=len(X), replace=True)
            model = GradientBoostingRegressor(
                n_estimators=int(cfg.get("n_estimators", 150)),
                max_depth=int(cfg.get("max_depth", 3)),
                learning_rate=float(cfg.get("learning_rate", 0.05)),
                random_state=seed + m,
            )
            model.fit(X[idx], y[idx])
            self.members.append(model)

        # Honest self-assessment: K-fold cross-validated Spearman.
        kf = KFold(n_splits=min(5, len(X)), shuffle=True, random_state=seed)
        preds = np.zeros(len(X))
        for train, test in kf.split(X):
            m = GradientBoostingRegressor(
                n_estimators=int(cfg.get("n_estimators", 150)),
                max_depth=int(cfg.get("max_depth", 3)),
                learning_rate=float(cfg.get("learning_rate", 0.05)),
                random_state=seed,
            )
            m.fit(X[train], y[train])
            preds[test] = m.predict(X[test])
        self.cv_spearman = float(stats.spearmanr(preds, y).statistic)
        self.n_train = len(X)

    def _features(self, texts: list[str]) -> np.ndarray:
        eng = np.array([feature_vector(t) for t in texts])
        emb = self.embedder.transform(texts)
        return np.hstack([eng, emb])

    def predict(self, text: str) -> tuple[float, float, float]:
        """Return (normalized_score_0_1, raw_prediction, ensemble_std)."""
        X = self._features([text])
        raw = np.array([m.predict(X)[0] for m in self.members])
        mean, std = float(raw.mean()), float(raw.std())
        span = (self.y_hi - self.y_lo) or 1.0
        norm = float(np.clip((mean - self.y_lo) / span, 0.0, 1.0))
        return norm, mean, std


def _cache_dir() -> Path:
    return Path(os.environ.get("CREATIVEGATE_CACHE_DIR", ".creativegate_cache"))


def _load_or_train(key: str, ctx) -> _TrainedModel:
    """Disk-persisted model cache so a server restart doesn't retrain.

    The pickle lives in a local cache dir this process writes itself — it is
    a performance cache inside one trust boundary, not an interchange format.
    Any read/unpickle failure falls back to retraining and overwriting.
    """
    path = _cache_dir() / f"predictor-{key}.pkl"
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            path.unlink(missing_ok=True)  # corrupt/stale cache: retrain
    model = _TrainedModel(ctx.ground_truth, ctx.target_metric, ctx.seed, ctx.config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(model, f)
    except OSError:
        pass  # read-only filesystem: in-memory cache still applies
    return model


def _fingerprint(gt: GroundTruthSet, metric: str, seed: int, cfg: dict) -> str:
    payload = json.dumps({
        "set": gt.name, "n": len(gt.records), "metric": metric, "seed": seed,
        "cfg": {k: v for k, v in cfg.items() if k != "threshold"},
        "features": FEATURE_VERSION,
    }, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class PerformancePredictor(Rung):
    name = "performance_predictor"
    version = RUNG_VERSION
    cost_tier = CostTier.CHEAP
    supported_modalities = (Modality.TEXT,)

    def _model(self, ctx: RungContext) -> Optional[_TrainedModel]:
        if ctx.ground_truth is None:
            return None
        key = _fingerprint(ctx.ground_truth, ctx.target_metric, ctx.seed, ctx.config)
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = _load_or_train(key, ctx)
        return _MODEL_CACHE[key]

    def evaluate(self, artifact: Artifact, ctx: RungContext) -> RungResult:
        if not artifact.text or ctx.ground_truth is None:
            return RungResult(
                rung=self.name, rung_version=self.version, score=None, passed=True,
                confidence=0.0, cost_tier=self.cost_tier,
                validity=self.stamped_validity(artifact, ctx),
                evidence=[Evidence(source=self.name, kind="flag",
                                   summary="Predictor skipped: no text or no ground-truth set.")],
                flags=["predictor_skipped"],
            )
        try:
            model = self._model(ctx)
        except ValueError as e:
            return RungResult(
                rung=self.name, rung_version=self.version, score=None, passed=True,
                confidence=0.0, cost_tier=self.cost_tier,
                validity=self.stamped_validity(artifact, ctx),
                evidence=[Evidence(source=self.name, kind="flag", summary=f"Predictor refused: {e}")],
                flags=["predictor_refused_insufficient_data"],
            )
        assert model is not None

        norm, raw, std = model.predict(artifact.text)
        span = (model.y_hi - model.y_lo) or 1.0
        rel_std = std / span

        evidence = [Evidence(
            source=self.name, kind="prediction",
            summary=(
                f"Predicted {ctx.target_metric}={raw:.4f} (+/- {std:.4f}, ensemble of "
                f"{len(model.members)}), normalized score {norm:.3f}. "
                f"Cross-val Spearman on training set: {model.cv_spearman:.2f} (n={model.n_train})."
            ),
            detail={
                "raw_prediction": raw, "ensemble_std": std, "normalized": norm,
                "cv_spearman": model.cv_spearman, "n_train": model.n_train,
                "feature_version": FEATURE_VERSION, "features": FEATURE_NAMES,
                "embedder": model.embedder.name,
            },
        )]

        threshold = ctx.config.get("threshold")
        passed = True if threshold is None else norm >= float(threshold)
        return RungResult(
            rung=self.name,
            rung_version=self.version,
            score=norm,
            passed=passed,
            confidence=max(0.0, 1.0 - 2.0 * rel_std),
            variance=rel_std ** 2,
            evidence=evidence,
            cost_tier=self.cost_tier,
            validity=self.stamped_validity(artifact, ctx),
            flags=[] if model.embedder.fidelity == "full" else ["degraded_provider: TF-IDF fallback embeddings"],
            provider_fidelity=model.embedder.fidelity,
        )
