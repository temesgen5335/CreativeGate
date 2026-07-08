"""Engineered features for text creatives.

Design rationale: one shared, versioned feature extractor feeds both the
performance predictor and the synthetic world. Keeping it in one module
guarantees that "the features the predictor learns on" and "the features the
synthetic world generates outcomes from" can only drift apart deliberately,
never accidentally.
"""

from __future__ import annotations

import re

FEATURE_VERSION = "0.1.0"

_CTA = re.compile(
    r"\b(shop|buy|get|try|start|learn more|sign up|order|discover|claim|download|join)\b", re.I
)
_URGENCY = re.compile(
    r"\b(now|today|hurry|limited|last chance|don't miss|only|sale|ends)\b", re.I
)
_BENEFIT = re.compile(r"\b(free|save|off|deal|bonus|exclusive|premium|easy|fast)\b", re.I)
_SPAMMY = re.compile(r"(!!+|\?\?+|100%|guaranteed|miracle|act now|risk.free)", re.I)
_QUESTION = re.compile(r"\?")
_NUMBER = re.compile(r"\d")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

FEATURE_NAMES = [
    "word_count",
    "char_count",
    "has_cta",
    "cta_count",
    "urgency_count",
    "benefit_count",
    "spam_count",
    "has_question",
    "has_number",
    "emoji_count",
    "avg_word_len",
    "caps_ratio",
    "exclaim_count",
]


def extract_features(text: str) -> dict[str, float]:
    words = text.split()
    n = max(len(words), 1)
    letters = [c for c in text if c.isalpha()]
    caps = sum(1 for c in letters if c.isupper())
    return {
        "word_count": float(len(words)),
        "char_count": float(len(text)),
        "has_cta": 1.0 if _CTA.search(text) else 0.0,
        "cta_count": float(len(_CTA.findall(text))),
        "urgency_count": float(len(_URGENCY.findall(text))),
        "benefit_count": float(len(_BENEFIT.findall(text))),
        "spam_count": float(len(_SPAMMY.findall(text))),
        "has_question": 1.0 if _QUESTION.search(text) else 0.0,
        "has_number": 1.0 if _NUMBER.search(text) else 0.0,
        "emoji_count": float(len(_EMOJI.findall(text))),
        "avg_word_len": sum(len(w) for w in words) / n,
        "caps_ratio": caps / max(len(letters), 1),
        "exclaim_count": float(text.count("!")),
    }


def feature_vector(text: str) -> list[float]:
    f = extract_features(text)
    return [f[name] for name in FEATURE_NAMES]
