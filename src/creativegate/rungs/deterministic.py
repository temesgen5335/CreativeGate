"""Rung 1: the Deterministic Gate.

Design rationale: free, instant, zero-variance hard checks. It catches
violations and never measures quality — its validity metadata says exactly
that, and its result carries ``score=None`` so fusion cannot mistake
"passed all rules" for "is good".

Checks are config, not code: banned phrases, required elements, structural
specs (length limits, image aspect ratio parsed straight from PNG/JPEG
headers — no imaging dependency), brand lexicon.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any, Optional

from ..schemas import Artifact, CostTier, Evidence, Modality, RungResult, Validity
from .base import Rung, RungContext

RUNG_VERSION = "0.1.0"


def _png_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return None


def _jpeg_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seg_len
    return None


def image_dimensions(path: str) -> Optional[tuple[int, int]]:
    data = Path(path).read_bytes()
    return _png_dimensions(data) or _jpeg_dimensions(data)


class DeterministicGate(Rung):
    name = "deterministic_gate"
    version = RUNG_VERSION
    cost_tier = CostTier.FREE
    supported_modalities = (Modality.TEXT, Modality.IMAGE, Modality.HTML, Modality.COMPOSITE)

    def evaluate(self, artifact: Artifact, ctx: RungContext) -> RungResult:
        cfg = ctx.config
        evidence: list[Evidence] = []
        failures = 0

        def check(name: str, ok: bool, summary: str, **detail: Any) -> None:
            nonlocal failures
            if not ok:
                failures += 1
            evidence.append(Evidence(
                source=self.name, kind="check",
                summary=f"{'PASS' if ok else 'FAIL'} [{name}]: {summary}",
                detail={"check": name, "passed": ok, **detail},
            ))

        text = artifact.text or ""

        for phrase in cfg.get("banned_phrases", []):
            hit = re.search(re.escape(phrase), text, re.I)
            check("banned_phrase", hit is None,
                  f"banned phrase '{phrase}'" + (" found" if hit else " absent"),
                  phrase=phrase)

        for pattern in cfg.get("banned_patterns", []):
            hit = re.search(pattern, text, re.I)
            check("banned_pattern", hit is None,
                  f"banned pattern '{pattern}'" + (f" matched '{hit.group(0)}'" if hit else " absent"),
                  pattern=pattern)

        for element in cfg.get("required_elements", []):
            # element: {"name": "cta", "pattern": "..."}
            ok = re.search(element["pattern"], text, re.I) is not None
            check("required_element", ok,
                  f"required element '{element['name']}'" + (" present" if ok else " missing"),
                  element=element["name"])

        max_chars = cfg.get("max_chars")
        if max_chars is not None:
            check("max_chars", len(text) <= max_chars,
                  f"length {len(text)} vs limit {max_chars}", length=len(text), limit=max_chars)

        min_words = cfg.get("min_words")
        if min_words is not None:
            n = len(text.split())
            check("min_words", n >= min_words,
                  f"{n} words vs minimum {min_words}", words=n, minimum=min_words)

        if artifact.path and artifact.modality == Modality.IMAGE:
            spec = cfg.get("image", {})
            dims = image_dimensions(artifact.path)
            if dims is None:
                check("image_parse", False, "could not parse image dimensions (png/jpeg header)")
            else:
                w, h = dims
                ratio_spec = spec.get("aspect_ratio")  # e.g. [1, 1] or [16, 9]
                if ratio_spec:
                    want = ratio_spec[0] / ratio_spec[1]
                    got = w / h
                    tol = spec.get("aspect_tolerance", 0.02)
                    check("aspect_ratio", abs(got - want) <= tol * want,
                          f"aspect {w}x{h} ({got:.3f}) vs spec {ratio_spec[0]}:{ratio_spec[1]}",
                          width=w, height=h)
                min_w = spec.get("min_width")
                if min_w:
                    check("min_width", w >= min_w, f"width {w} vs minimum {min_w}")
            max_bytes = spec.get("max_bytes")
            if max_bytes:
                size = Path(artifact.path).stat().st_size
                check("max_bytes", size <= max_bytes, f"file {size}B vs limit {max_bytes}B")

        passed = failures == 0
        return RungResult(
            rung=self.name,
            rung_version=self.version,
            score=None,  # gates never claim quality
            passed=passed,
            confidence=1.0,  # zero variance: it is what it checks
            evidence=evidence,
            cost_tier=self.cost_tier,
            validity=Validity(
                calibrated=False,
                statement=(
                    "Deterministic gate: catches violations, never measures quality. "
                    "Binary checks carry no fusion weight by design."
                ),
            ),
            flags=[] if passed else [f"{failures} deterministic check(s) failed"],
            provider_fidelity="full",
        )

    def predict_outcome(self, artifact: Artifact, ctx: RungContext) -> Optional[float]:
        return None  # gates produce no outcome-correlated score
