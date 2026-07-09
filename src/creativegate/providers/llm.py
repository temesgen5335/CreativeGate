"""LLM provider slot with a multi-provider fallback chain.

Design rationale: the judge rung needs *some* comparator. With API keys it
gets real LLMs — every configured provider (all via OpenAI-compatible
endpoints) forms a priority chain, and a provider that errors is put on a
short cooldown while the next one answers. The chain always terminates in
``NullLLM`` — a deterministic, feature-heuristic comparator that cannot fail
— so a provider outage degrades fidelity instead of erroring the evaluation.
Models are enhancers, never dependencies.

Honesty contract: the chain reports which provider actually answered and
whether any comparison fell through to the heuristic; the judge stamps that
into the verdict's evidence and ``provider_fidelity``. The calibration
harness then measures what the comparator — whichever one ran — is actually
worth. Nothing downstream assumes which provider answered.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
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


class FallbackLLM(LLMProvider):
    """Priority chain of providers ending in NullLLM.

    A provider that raises goes on cooldown and the next answers. ``name``
    and ``fidelity`` reflect what actually served comparisons so far, so a
    judge reading them after its ensemble passes reports truthfully.
    """

    COOLDOWN_S = 60.0

    def __init__(self, providers: list[LLMProvider]):
        self.chain: list[LLMProvider] = list(providers) + [NullLLM()]
        self._cooldown_until: dict[int, float] = {}
        self._used: list[str] = []
        self._null_used = False
        self.name = self.chain[0].name
        self.fidelity = self.chain[0].fidelity

    def _record(self, provider: LLMProvider) -> None:
        if provider.name not in self._used:
            self._used.append(provider.name)
        if isinstance(provider, NullLLM):
            self._null_used = True
        self.name = " → ".join(self._used)
        self.fidelity = "degraded" if self._null_used else "full"

    def compare(self, prompt: str, a: str, b: str, seed: int) -> str:
        now = time.monotonic()
        for i, provider in enumerate(self.chain):
            if self._cooldown_until.get(i, 0.0) > now:
                continue
            try:
                answer = provider.compare(prompt, a, b, seed)
                self._record(provider)
                return answer
            except Exception:
                self._cooldown_until[i] = now + self.COOLDOWN_S
        # Unreachable in practice (NullLLM never raises), but never fail the rung:
        terminal = self.chain[-1]
        self._record(terminal)
        return terminal.compare(prompt, a, b, seed)


# Known OpenAI-compatible providers, default priority order (top first):
# (id, key env, model env, default model, base URL)
PROVIDER_SPECS = [
    ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini",
     "https://api.openai.com/v1"),
    ("groq", "GROQ_API_KEY", "GROQ_MODEL", "llama-3.1-8b-instant",
     "https://api.groq.com/openai/v1"),
    ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.0-flash",
     "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("openrouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct",
     "https://openrouter.ai/api/v1"),
    ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001",
     "https://api.anthropic.com/v1"),
]


def _env_providers() -> list[OpenAICompatibleLLM]:
    """Build the provider list from the environment, preference first.

    ``LLM_PROVIDER`` (or ``CREATIVEGATE_LLM_PROVIDER``) names the preferred
    provider; the remaining configured ones follow in default order as
    fallbacks. ``CREATIVEGATE_LLM_*`` defines a custom OpenAI-compatible
    endpoint and always ranks first when present.
    """
    providers: list[OpenAICompatibleLLM] = []
    custom_key = os.environ.get("CREATIVEGATE_LLM_API_KEY")
    if custom_key:
        providers.append(OpenAICompatibleLLM(
            api_key=custom_key,
            model=os.environ.get("CREATIVEGATE_LLM_MODEL", "gpt-4o-mini"),
            base_url=os.environ.get("CREATIVEGATE_LLM_BASE_URL", "https://api.openai.com/v1"),
        ))
    preferred = (os.environ.get("CREATIVEGATE_LLM_PROVIDER")
                 or os.environ.get("LLM_PROVIDER") or "").strip().lower()
    specs = sorted(PROVIDER_SPECS, key=lambda s: 0 if s[0] == preferred else 1)
    for pid, key_env, model_env, default_model, base_url in specs:
        key = os.environ.get(key_env)
        if key:
            providers.append(OpenAICompatibleLLM(
                api_key=key,
                model=os.environ.get(model_env, default_model),
                base_url=base_url,
            ))
    return providers


def resolve_llm(config: Optional[dict] = None) -> LLMProvider:
    """Build the best available comparator; degrade keylessly to NullLLM.

    Explicit rung config wins outright; otherwise every provider configured
    in the environment joins a fallback chain (preference via LLM_PROVIDER).
    With zero keys this returns the bare deterministic heuristic.
    """
    config = config or {}
    if config.get("api_key"):
        return FallbackLLM([OpenAICompatibleLLM(
            api_key=config["api_key"],
            model=config.get("model", "gpt-4o-mini"),
            base_url=config.get("base_url", "https://api.openai.com/v1"),
        )])
    providers = _env_providers()
    return FallbackLLM(providers) if providers else NullLLM()
