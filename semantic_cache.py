"""
Semantic query cache.

The exact pipeline cache (md5 of query+category+weights+Q&A) only hits when a query is
*character-identical*. But "best gym earbuds" and "earbuds for working out" should reuse
the same research — they are the same intent. This module sits in front of the pipeline
cache: it embeds the query and, when a recent search with the same category, region, and
rubric fingerprint had a query within cosine ≥ 0.95, returns that search's pipeline cache
key so the whole ~85s research run is skipped.

Safety: a hit requires identical category + region + rubric fingerprint, so we never serve
a result scored against a different user's priorities — only genuine near-duplicate intent.

Cost: one embed() call per search. embed() has an in-flight-dedup + file cache, so repeat
queries cost nothing. The index stores vectors inline, capped at _MAX_ENTRIES and pruned by
TTL on every access, so it stays small (only queries from the last few hours).
"""

from __future__ import annotations

import time

import cache
from embeddings import embed, cosine_similarity

_INDEX_TYPE = "semantic_cache"
_INDEX_KEY = "query_index"
_MAX_ENTRIES = 50
_SIM_THRESHOLD = 0.95
_TTL_SECONDS = 4 * 3600  # match the pipeline cache TTL


def fingerprint(rubric: dict) -> list:
    """
    Stable signature of a rubric's weights — two rubrics with the same rounded weights match.
    Returns a list of [name, weight] lists (not tuples) so it survives JSON round-trips through
    the file cache and compares equal to a reloaded index entry.
    """
    return sorted(
        [c.get("name", ""), round(float(c.get("weight", 0.0)))]
        for c in (rubric.get("weighted_criteria") or [])
    )


def _norm(query: str) -> str:
    return query.lower().strip()


def _load_index() -> list[dict]:
    idx = cache.get(_INDEX_TYPE, _INDEX_KEY)
    if not isinstance(idx, list):
        return []
    now = time.time()
    return [e for e in idx if isinstance(e, dict) and now - e.get("ts", 0) <= _TTL_SECONDS]


def _save_index(entries: list[dict]) -> None:
    cache.set(_INDEX_TYPE, _INDEX_KEY, entries[-_MAX_ENTRIES:])


def lookup(query: str, category: str, region: str, rubric_fingerprint: list) -> str | None:
    """
    Return the pipeline cache key of a semantically-equivalent recent search, or None.
    A match requires same category + region + rubric fingerprint AND query cosine ≥ 0.95.
    """
    try:
        emb = embed(_norm(query))
        if not emb:
            return None
        best_key: str | None = None
        best_sim = _SIM_THRESHOLD
        for e in _load_index():
            if e.get("category") != category or e.get("region") != region:
                continue
            if e.get("fingerprint") != rubric_fingerprint:
                continue
            sim = cosine_similarity(emb, e.get("embedding") or [])
            if sim >= best_sim:
                best_sim = sim
                best_key = e.get("cache_key")
        return best_key
    except Exception:
        return None


def register(query: str, category: str, region: str, rubric_fingerprint: list, cache_key: str) -> None:
    """Record this completed search so future near-identical queries can reuse it."""
    try:
        emb = embed(_norm(query))
        if not emb:
            return
        # Drop any prior entry pointing at the same cache_key, then append the fresh one.
        entries = [e for e in _load_index() if e.get("cache_key") != cache_key]
        entries.append({
            "query": _norm(query),
            "category": category,
            "region": region,
            "fingerprint": rubric_fingerprint,
            "embedding": emb,
            "cache_key": cache_key,
            "ts": time.time(),
        })
        _save_index(entries)
    except Exception:
        pass
