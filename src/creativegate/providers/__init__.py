"""Provider slots (LLM, embeddings) with keyless degradation.

Design rationale: models are enhancers, never dependencies. Every slot has a
deterministic zero-key fallback so the funnel always produces a verdict —
clearly labeled ``provider_fidelity="degraded"`` when the fallback is used.
"""

from .llm import LLMProvider, NullLLM, OpenAICompatibleLLM, resolve_llm
from .embeddings import EmbeddingProvider, TfidfEmbeddings, resolve_embeddings

__all__ = [
    "LLMProvider",
    "NullLLM",
    "OpenAICompatibleLLM",
    "resolve_llm",
    "EmbeddingProvider",
    "TfidfEmbeddings",
    "resolve_embeddings",
]
