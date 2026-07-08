"""LLM provider slot.

Design rationale: the judge rung needs *some* comparator. With an API key it
gets a real LLM (any OpenAI-compatible endpoint, temperature 0). Without one
it gets ``NullLLM`` — a deterministic, feature-heuristic comparator that is
honest about being a low-fidelity stand-in. The judge rung reports
``provider_fidelity`` accordingly; the calibration harness then measures how
much either comparator is actually worth. Nothing downstream assumes which
one ran.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Optional

import httpx


class LLMProvider(ABC):
    """Answers a pairwise creative-comparison prompt with 'A' or 'B'."""

    name: str = "abstract"
    fidelity: str = "full"

    @abstractmethod
    def compare(self, prompt: str, a: str, b: str, seed: int) -> str:
        """Return 'A' or 'B': which creative is more likely to perform."""


_URGENCY = re.compile(
    r"\b(now|today|hurry|limited|last chance|don't miss|only|sale|free|save|new)\b", re.I
)
_CTA = re.compile(
    r"\b(shop|buy|get|try|start|learn more|sign up|order|discover|claim|download|join)\b", re.I
)
_SPAMMY = re.compile(r"(!!+|\?\?+|100% |guaranteed|miracle|act now)", re.I)


def _heuristic_appeal(text: str) -> float:
    """Deterministic proxy for creative appeal. Deliberately simple; its
    worth is measured by the calibration harness, not assumed."""
    words = text.split()
    n = len(words)
    score = 0.0
    score += 0.30 * min(len(_CTA.findall(text)), 2)
    score += 0.20 * min(len(_URGENCY.findall(text)), 3)
    score += 0.25 if 6 <= n <= 24 else (0.05 if n <= 40 else -0.10)
    score -= 0.35 * len(_SPAMMY.findall(text))
    score += 0.10 if text[:1].isupper() else 0.0
    score -= 0.15 if text.isupper() else 0.0
    return score


class NullLLM(LLMProvider):
    """Zero-key deterministic comparator. Ties break by content hash so the
    result is stable across runs and platforms."""

    name = "null-heuristic"
    fidelity = "degraded"

    def compare(self, prompt: str, a: str, b: str, seed: int) -> str:
        sa, sb = _heuristic_appeal(a), _heuristic_appeal(b)
        if abs(sa - sb) > 1e-9:
            return "A" if sa > sb else "B"
        h = hashlib.sha256(f"{seed}:{a}|{b}".encode()).digest()[0]
        return "A" if h % 2 == 0 else "B"


class OpenAICompatibleLLM(LLMProvider):
    """Any OpenAI-compatible chat endpoint, temperature 0."""

    fidelity = "full"

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"openai-compatible:{model}"

    def compare(self, prompt: str, a: str, b: str, seed: int) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "seed": seed,
            "max_tokens": 4,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Creative A:\n{a}\n\nCreative B:\n{b}\n\n"
                        "Answer with exactly one character: A or B."
                    ),
                },
            ],
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return "A" if content.startswith("A") else "B"


def resolve_llm(config: Optional[dict] = None) -> LLMProvider:
    """Pick the best available provider; degrade keylessly to NullLLM."""
    config = config or {}
    api_key = config.get("api_key") or os.environ.get("CREATIVEGATE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        return OpenAICompatibleLLM(
            api_key=api_key,
            model=config.get("model", os.environ.get("CREATIVEGATE_LLM_MODEL", "gpt-4o-mini")),
            base_url=config.get("base_url", os.environ.get("CREATIVEGATE_LLM_BASE_URL", "https://api.openai.com/v1")),
        )
    return NullLLM()
