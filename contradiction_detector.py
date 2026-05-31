"""
Phase 7: Cross-review contradiction detection.

Scans all review contents for opposing sentiment claims about specific product
aspects. When two or more reviews disagree on an aspect, that gets flagged as
a conflict so the analyzer can explicitly mention "experts disagree on X."

Output per aspect that has ≥ 3 data points:
  {
    "topic": "battery_life",
    "agreement_score": 0.54,   # fraction that agree with the majority view
    "conflict": True,          # True if agreement < 0.75
    "positive_count": 3,
    "negative_count": 4,
  }

Falls back to [] on any failure — never disrupts the main pipeline.
"""

from __future__ import annotations

import re
from collections import defaultdict


# ---------------------------------------------------------------------------
# Aspect definitions — keyword patterns that indicate the review is discussing
# a specific product dimension.
# ---------------------------------------------------------------------------

_ASPECTS: dict[str, list[str]] = {
    "battery_life": [
        r"\bbatter(?:y|ies)\b", r"\bendurance\b", r"\bcharge\s*time\b",
        r"\bmah\b", r"\bstandby\b", r"\blife\s*(?:cycle|span)\b",
    ],
    "display": [
        r"\bdisplay\b", r"\bscreen\b", r"\bpanel\b", r"\bnits\b",
        r"\bbrightness\b", r"\bcontrast\b", r"\bcolor\s*accuracy\b",
        r"\brefresh\s*rate\b", r"\bhz\b",
    ],
    "performance": [
        r"\bperformance\b", r"\bprocessor\b", r"\bcpu\b", r"\bgpu\b",
        r"\blag\b", r"\bbenchmark\b", r"\bspeed\b", r"\bthrottle\b",
    ],
    "build_quality": [
        r"\bbuild\s*quality\b", r"\bconstruction\b", r"\bdurability\b",
        r"\bpremium\s*feel\b", r"\bplastic\b", r"\bmetal\b", r"\bflimsy\b",
    ],
    "sound_quality": [
        r"\bsound\s*quality\b", r"\baudio\b", r"\bbass\b", r"\btreble\b",
        r"\bnoise\s*cancell\b", r"\banc\b", r"\bspeaker\b",
    ],
    "value": [
        r"\bvalue\b", r"\boverpriced\b", r"\baffordable\b", r"\bworth\b",
        r"\bprice[:\s]", r"\bcost[:\s]",
    ],
    "thermals": [
        r"\bheat\b", r"\bthermal\b", r"\boverheating\b", r"\btemperature\b",
        r"\bwarm\b", r"\bcooling\b",
    ],
    "camera": [
        r"\bcamera\b", r"\bphoto\b", r"\bvideo\b", r"\bimage\s*quality\b",
        r"\bautofocus\b", r"\bnight\s*mode\b",
    ],
    "software": [
        r"\bsoftware\b", r"\bos\b", r"\bbloatware\b", r"\bupdates?\b",
        r"\bbug\b", r"\bui\b", r"\binterface\b",
    ],
}

# Sentiment signal words for context windows around aspect mentions
_POSITIVE = [
    r"\bexcellent\b", r"\boutstanding\b", r"\bimpressive\b", r"\bgreat\b",
    r"\bgood\b", r"\bsolid\b", r"\bstrong\b", r"\blong\b", r"\bbright\b",
    r"\bsharp\b", r"\bfast\b", r"\bsmooth\b", r"\baccurate\b", r"\bpremium\b",
    r"\bworth(?:while)?\b", r"\bvalue\s*for\s*money\b", r"\bexceptional\b",
    r"\bpleasant\b", r"\bsatisf(?:ying|ied|actory)\b",
]

_NEGATIVE = [
    r"\bpoor\b", r"\bweak\b", r"\bdisappointing\b", r"\bshort\b", r"\bdim\b",
    r"\bblurry\b", r"\bslow\b", r"\blaggy\b", r"\boverheating\b", r"\bhot\b",
    r"\boverpriced\b", r"\bflimsy\b", r"\bmediocre\b", r"\baverage\b",
    r"\bcheap\s*feel\b", r"\bpoor\s*quality\b", r"\bunreliable\b",
    r"\bbloatware\b", r"\bbuggy\b", r"\bfrustrat\b",
]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MIN_DATAPOINTS = 3     # minimum signals before reporting a topic
_CONFLICT_THRESHOLD = 0.75  # < 75% majority = conflict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_review_conflicts(reviews: list[dict]) -> list[dict]:
    """
    Scan all review contents and detect contradictions per product aspect.

    Returns sorted list of conflict signals (most contentious first).
    Returns [] if fewer than 2 reviews or any failure occurs.
    """
    if len(reviews) < 2:
        return []
    try:
        return _detect(reviews)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

# Pre-compile all patterns once at module load
_COMPILED_ASPECTS: dict[str, list[re.Pattern]] = {
    aspect: [re.compile(p, re.IGNORECASE) for p in pats]
    for aspect, pats in _ASPECTS.items()
}
_COMPILED_POS = [re.compile(p, re.IGNORECASE) for p in _POSITIVE]
_COMPILED_NEG = [re.compile(p, re.IGNORECASE) for p in _NEGATIVE]


def _detect(reviews: list[dict]) -> list[dict]:
    # aspect → list of "positive" | "negative"
    aspect_signals: dict[str, list[str]] = defaultdict(list)

    for review in reviews:
        content = (review.get("content") or "").lower()
        if len(content) < 20:
            continue
        _scan_review(content, aspect_signals)

    results = []
    for aspect, signals in aspect_signals.items():
        pos = signals.count("positive")
        neg = signals.count("negative")
        total = pos + neg
        if total < _MIN_DATAPOINTS:
            continue
        majority_frac = max(pos, neg) / total
        results.append({
            "topic": aspect,
            "agreement_score": round(majority_frac, 2),
            "conflict": majority_frac < _CONFLICT_THRESHOLD,
            "positive_count": pos,
            "negative_count": neg,
        })

    # Sort by most contentious (lowest agreement) first
    results.sort(key=lambda x: x["agreement_score"])
    return results


def _scan_review(content: str, out: dict[str, list[str]]) -> None:
    # Sentence-level analysis: evaluate sentiment per sentence to avoid cross-sentence
    # contamination (e.g. "great battery. dim display." → battery=pos, display=neg, not mixed).
    sentences = _SENTENCE_SPLIT.split(content)
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 8:
            continue

        pos_hits = sum(1 for p in _COMPILED_POS if p.search(sent))
        neg_hits = sum(1 for p in _COMPILED_NEG if p.search(sent))
        if pos_hits == neg_hits:
            continue  # no clear sentiment signal in this sentence

        sentiment = "positive" if pos_hits > neg_hits else "negative"

        for aspect, pats in _COMPILED_ASPECTS.items():
            if any(p.search(sent) for p in pats):
                out[aspect].append(sentiment)
