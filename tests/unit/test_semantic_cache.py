"""
Unit tests for semantic_cache — the near-duplicate-query reuse layer.

Embeddings are stubbed (no network) so we test the match/miss policy deterministically:
a hit requires same category + region + rubric fingerprint AND query cosine >= 0.95.
"""

from __future__ import annotations

import pytest

import semantic_cache as sc
import cache


_VECS = {
    "best gym earbuds":        [1.0, 0.0, 0.0],
    "earbuds for working out": [0.98, 0.20, 0.0],   # ~0.98 cosine with gym earbuds
    "earbuds for the office":  [0.30, 0.95, 0.0],    # ~0.30 cosine — below threshold
    "best laptop for coding":  [0.0, 1.0, 0.0],      # orthogonal
}


@pytest.fixture(autouse=True)
def _stub_embed_and_clear(monkeypatch):
    monkeypatch.setattr(sc, "embed", lambda q: _VECS.get(q.lower().strip()))
    cache.set(sc._INDEX_TYPE, sc._INDEX_KEY, [])
    yield
    cache.set(sc._INDEX_TYPE, sc._INDEX_KEY, [])


_RUBRIC = {"weighted_criteria": [{"name": "sound", "weight": 9.0}, {"name": "battery", "weight": 7.0}]}


def _fp(r=_RUBRIC):
    return sc.fingerprint(r)


def test_paraphrase_hits():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_ABC")
    assert sc.lookup("earbuds for working out", "electronics/earbuds", "india", fp) == "KEY_ABC"


def test_dissimilar_query_misses():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_ABC")
    # cosine ~0.30 — well below the 0.95 threshold
    assert sc.lookup("earbuds for the office", "electronics/earbuds", "india", fp) is None


def test_different_category_misses():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_ABC")
    assert sc.lookup("earbuds for working out", "electronics/laptop", "india", fp) is None


def test_different_region_misses():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_ABC")
    assert sc.lookup("earbuds for working out", "electronics/earbuds", "usa", fp) is None


def test_different_rubric_misses():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_ABC")
    other_fp = sc.fingerprint({"weighted_criteria": [{"name": "sound", "weight": 2.0}]})
    assert sc.lookup("earbuds for working out", "electronics/earbuds", "india", other_fp) is None


def test_fingerprint_survives_json_roundtrip():
    """Fingerprint must be list-of-lists (not tuples) so it compares equal after cache reload."""
    import json
    fp = sc.fingerprint(_RUBRIC)
    assert fp == json.loads(json.dumps(fp)), "fingerprint must be JSON-idempotent"


def test_exact_same_query_hits():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_XYZ")
    assert sc.lookup("best gym earbuds", "electronics/earbuds", "india", fp) == "KEY_XYZ"


def test_register_dedups_same_cache_key():
    fp = _fp()
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_1")
    sc.register("best gym earbuds", "electronics/earbuds", "india", fp, "KEY_1")
    entries = [e for e in sc._load_index() if e.get("cache_key") == "KEY_1"]
    assert len(entries) == 1, "re-registering the same cache_key must not duplicate the entry"
