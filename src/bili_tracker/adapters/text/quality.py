from __future__ import annotations

import re

from bili_tracker.domain.ports import QualityGate, QualityVerdict


class DeterministicQualityGate(QualityGate):
    id = "deterministic"

    def __init__(self, min_coverage: float = 0.2, max_expansion: float = 3.0) -> None:
        self.min_coverage = min_coverage
        self.max_expansion = max_expansion

    def evaluate(self, original: str, candidate: str) -> QualityVerdict:
        original = original.strip()
        candidate = candidate.strip()
        if not candidate:
            return QualityVerdict(False, "quality.empty_output", {})
        if not original:
            return QualityVerdict(True, "quality.no_original", {})
        ratio = len(candidate) / len(original)
        if ratio < self.min_coverage:
            return QualityVerdict(False, "quality.coverage_low", {"ratio": ratio})
        if ratio > self.max_expansion:
            return QualityVerdict(False, "quality.expansion_high", {"ratio": ratio})
        longest = max((len(part) for part in re.split(r"[。！？.!?\n]", candidate)), default=0)
        if longest > 1200:
            return QualityVerdict(False, "quality.paragraph_too_long", {"length": longest})
        return QualityVerdict(True, "quality.ok", {"coverage_ratio": ratio})
