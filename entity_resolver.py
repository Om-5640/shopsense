"""
Phase 6: Product entity resolution.

Groups product name variants into canonical entities so all evidence aggregates
to a single product rather than being split across spelling variants.

Examples:
  "ASUS TUF A15" + "ASUS TUF Gaming A15"  → canonical: "ASUS TUF Gaming A15"
  "FA507NV" + "FA507NU"                   → treated separately (different SKUs)
  "Sony WF-1000XM5" + "WF1000XM5"        → same canonical entity

Algorithm:
  1. Tokenize each name, remove stop words
  2. Compute pairwise Jaccard similarity
  3. Cluster at similarity ≥ threshold (default 0.55)
  4. Pick the longest/most-complete name as canonical

Falls back silently — products keep original names if resolution fails.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "for", "of", "with", "in", "on",
    "best", "top", "new", "review", "vs", "versus", "compare",
    "buy", "price", "deal", "cheap", "budget", "premium", "latest",
}

# Characters to treat as token separators in product names
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_product_entities(
    products: list[dict],
    name_field: str = "name",
    threshold: float = 0.55,
) -> list[dict]:
    """
    Add canonical_product_id and canonical_product_name to each product dict.

    Modifies dicts in-place and returns the list for chaining.
    Falls back gracefully: if resolution fails, products keep original names
    as their canonical identity.
    """
    if not products:
        return products
    try:
        return _resolve(products, name_field, threshold)
    except Exception:
        # Fallback: set canonical fields to original names so downstream
        # code can always assume these keys exist.
        for p in products:
            name = p.get(name_field, "")
            p.setdefault("canonical_product_id", _slug(name))
            p.setdefault("canonical_product_name", name)
        return products


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _resolve(products: list[dict], name_field: str, threshold: float) -> list[dict]:
    names = [p.get(name_field, "") for p in products]
    groups = _cluster(names, threshold)

    # name → (canonical_id, canonical_name)
    lookup: dict[str, tuple[str, str]] = {}
    for group in groups:
        canon = _best_name(group)
        cid = _slug(canon)
        for n in group:
            lookup[n] = (cid, canon)

    for p in products:
        name = p.get(name_field, "")
        cid, cname = lookup.get(name, (_slug(name), name))
        p["canonical_product_id"] = cid
        p["canonical_product_name"] = cname

    return products


def _tokenize(name: str) -> frozenset[str]:
    tokens = _TOKEN_RE.findall(name.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS and len(t) >= 2)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cluster(names: list[str], threshold: float) -> list[list[str]]:
    if not names:
        return []
    token_sets = [_tokenize(n) for n in names]
    assigned = [False] * len(names)
    clusters: list[list[str]] = []

    for i, name in enumerate(names):
        if assigned[i]:
            continue
        group = [name]
        assigned[i] = True
        for j in range(i + 1, len(names)):
            if assigned[j]:
                continue
            if _jaccard(token_sets[i], token_sets[j]) >= threshold:
                group.append(names[j])
                assigned[j] = True
        clusters.append(group)

    return clusters


def _best_name(group: list[str]) -> str:
    """Pick the most descriptive name: prefer most tokens, then longest string."""
    if len(group) == 1:
        return group[0]
    return max(group, key=lambda n: (len(_tokenize(n)), len(n)))


def _slug(name: str) -> str:
    """Stable lowercase slug for a product name."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if len(s) > 60:
        suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        s = s[:50].rstrip("_") + "_" + suffix
    return s or "unknown_product"
