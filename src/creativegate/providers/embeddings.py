"""Embedding provider slot.

Design rationale: the performance predictor wants a dense representation of
artifact text. The zero-key fallback is deterministic TF-IDF + truncated SVD
fit on the ground-truth corpus — reproducible, no downloads, no keys. A
sentence-transformers or API provider can replace it without touching the
predictor, because the interface is just fit/transform over strings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer


class EmbeddingProvider(ABC):
    name: str = "abstract"
    fidelity: str = "full"

    @abstractmethod
    def fit(self, corpus: list[str]) -> None: ...

    @abstractmethod
    def transform(self, texts: list[str]) -> np.ndarray: ...


class TfidfEmbeddings(EmbeddingProvider):
    """Deterministic TF-IDF -> SVD embeddings. Zero keys, zero variance."""

    name = "tfidf-svd"
    fidelity = "degraded"

    def __init__(self, dim: int = 16, seed: int = 7):
        self.dim = dim
        self.seed = seed
        self._vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self._svd: TruncatedSVD | None = None

    def fit(self, corpus: list[str]) -> None:
        X = self._vec.fit_transform(corpus)
        dim = max(2, min(self.dim, X.shape[1] - 1, X.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=dim, random_state=self.seed)
        self._svd.fit(X)

    def transform(self, texts: list[str]) -> np.ndarray:
        if self._svd is None:
            raise RuntimeError("TfidfEmbeddings.transform called before fit()")
        return self._svd.transform(self._vec.transform(texts))


def resolve_embeddings(config: dict | None = None, seed: int = 7) -> EmbeddingProvider:
    """v0.1 ships the deterministic fallback only; API/local slots plug in here."""
    config = config or {}
    return TfidfEmbeddings(dim=int(config.get("dim", 16)), seed=seed)
