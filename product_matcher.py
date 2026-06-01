"""
Product Matcher (Phase 5) — highest-priority module.

Compares a CanonicalProduct (the target) against a raw candidate title
and returns a structured match score.

Scoring formula:
  overall = model×0.40 + storage×0.20 + ram×0.15 + brand×0.15 + color×0.05 + title_sim×0.05

Storage mismatch → hard penalty (score ×0.30), preventing wrong-SKU returns.
< 5ms per candidate.
"""

import re
from dataclasses import dataclass

from product_canonicalizer import CanonicalProduct, canonicalize_product

__all__ = ["MatchResult", "match_product_candidate"]


@dataclass
class MatchResult:
    brand_match: float
    model_match: float
    storage_match: float
    ram_match: float
    color_match: float
    title_similarity: float
    overall_match_score: float
    storage_mismatch: bool   # True → wrong storage variant


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _jaccard(a: str | None, b: str | None) -> float:
    """Token-level Jaccard similarity. Returns 0.5 when either side is unknown."""
    if not a or not b:
        return 0.5
    a_tok = set(re.sub(r"[^a-z0-9]", " ", a.lower()).split())
    b_tok = set(re.sub(r"[^a-z0-9]", " ", b.lower()).split())
    if not a_tok or not b_tok:
        return 0.5
    return len(a_tok & b_tok) / len(a_tok | b_tok)


def _to_gb(s: str) -> float | None:
    """Parse a storage string to float GB for numeric comparison."""
    s = s.upper().strip()
    m = re.search(r"[\d.]+", s)
    if not m:
        return None
    val = float(m.group())
    if "TB" in s:
        return val * 1024.0
    if "GB" in s:
        return val
    if "MB" in s:
        return val / 1024.0
    return None


def _storage_score(a: str | None, b: str | None) -> tuple[float, bool]:
    """
    Returns (score, is_mismatch).
    - Both None  → (1.0, False) — no storage info, neutral
    - One None   → (0.5, False) — partial credit
    - Same GB    → (1.0, False)
    - Different  → (0.0, True)  — hard mismatch
    """
    if not a and not b:
        return (1.0, False)
    if not a or not b:
        return (0.5, False)

    a_gb = _to_gb(a)
    b_gb = _to_gb(b)
    if a_gb is None or b_gb is None:
        return (0.5, False)

    if abs(a_gb - b_gb) < 0.5:   # same (within rounding)
        return (1.0, False)

    return (0.0, True)


def _model_score(a: str | None, b: str | None) -> float:
    """Model string similarity with exact/substring bonuses."""
    if not a or not b:
        return 0.5
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return 1.0
    if al in bl or bl in al:
        return max(_jaccard(a, b), 0.80)
    return _jaccard(a, b)


def _brand_score(a: str | None, b: str | None) -> float:
    """Brand comparison — exact=1.0, substring=0.8, no match=0.0, unknown=0.5."""
    if not a or not b:
        return 0.5
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return 1.0
    if al in bl or bl in al:
        return 0.8
    return 0.0


def _color_score(a: str | None, b: str | None) -> float:
    """Color comparison — missing color = no penalty (returns 1.0)."""
    if not a or not b:
        return 1.0   # unknown color never penalizes
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return 1.0
    # Partial: "Titanium Black" matches "Black"
    if al in bl or bl in al:
        return 0.7
    # Core color word overlap
    a_core = al.split()[-1]   # last word = base color
    b_core = bl.split()[-1]
    if a_core == b_core:
        return 0.6
    return 0.0


def _ram_score(a: str | None, b: str | None) -> float:
    """RAM comparison — unknown = neutral 0.5, same = 1.0, different = 0.2."""
    if not a or not b:
        return 0.5
    a_gb = _to_gb(a)
    b_gb = _to_gb(b)
    if a_gb is None or b_gb is None:
        return 0.5
    if abs(a_gb - b_gb) < 0.5:
        return 1.0
    return 0.2   # RAM mismatch is less severe than storage mismatch


# ── Public API ────────────────────────────────────────────────────────────────

def match_product_candidate(canonical: CanonicalProduct, candidate_title: str) -> MatchResult:
    """
    Phase 5: Compare a CanonicalProduct (target) against a raw title string.

    Returns MatchResult with per-field scores and overall_match_score.
    Storage mismatch triggers a 70% penalty on the overall score.

    Example:
        canonical = canonicalize_product("Samsung Galaxy S25 Ultra 512GB")
        result    = match_product_candidate(canonical, "Samsung Galaxy S25 Ultra 256GB Titanium Black")
        # result.storage_mismatch = True
        # result.overall_match_score ≈ 0.24  (penalized)
    """
    if not candidate_title or not candidate_title.strip():
        return MatchResult(
            brand_match=0.0, model_match=0.0, storage_match=0.0, ram_match=0.0,
            color_match=0.0, title_similarity=0.0, overall_match_score=0.0,
            storage_mismatch=False,
        )

    cand = canonicalize_product(candidate_title)

    brand   = _brand_score(canonical.brand, cand.brand)
    model   = _model_score(canonical.model, cand.model)
    storage, storage_mismatch = _storage_score(canonical.storage, cand.storage)
    ram     = _ram_score(canonical.ram, cand.ram)
    color   = _color_score(canonical.color, cand.color)
    title_sim = _jaccard(canonical.canonical_name, candidate_title)

    raw = (
        model   * 0.40
        + storage * 0.20
        + ram     * 0.15
        + brand   * 0.15
        + color   * 0.05
        + title_sim * 0.05
    )

    # Storage mismatch → heavy penalty so wrong variants never win
    overall = raw * 0.30 if storage_mismatch else raw

    return MatchResult(
        brand_match=round(brand, 3),
        model_match=round(model, 3),
        storage_match=round(storage, 3),
        ram_match=round(ram, 3),
        color_match=round(color, 3),
        title_similarity=round(title_sim, 3),
        overall_match_score=round(overall, 3),
        storage_mismatch=storage_mismatch,
    )
