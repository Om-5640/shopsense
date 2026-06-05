"""
Unit tests for evidence_enricher — the targeted per-product-per-criterion gap filler.

Serper and the LLM are stubbed, so we test the policy deterministically (no network):
gap selection, fetch fan-out, strict patching (only fills asked-for no-data gaps), and the
guarantee that any failure / disabled flag returns the input scored list unchanged.
"""

from __future__ import annotations

import pytest

import evidence_enricher as ee


@pytest.fixture(autouse=True)
def _no_network_deep_fetch(monkeypatch):
    """Deep-read hits the live Jina API — disable it by default so unit tests stay offline.
    The dedicated test below re-enables it with a mocked reader."""
    monkeypatch.setattr(ee, "ENABLE_DEEP_FETCH", False)


def _scored():
    # Two products; several criteria have data, several are no-data gaps.
    return [
        {"name": "iQOO Z9x", "scores": [
            {"criterion": "camera",  "label": "Camera",  "weight": 9, "score": 6, "evidence": "64MP", "has_data": True},
            {"criterion": "display", "label": "Display", "weight": 7, "score": 4, "evidence": "[NO DATA]", "has_data": False},
            {"criterion": "water",   "label": "Water",   "weight": 6, "score": 4, "evidence": "[NO DATA]", "has_data": False},
        ]},
        {"name": "Moto Edge 60", "scores": [
            {"criterion": "camera",  "label": "Camera",  "weight": 9, "score": 8, "evidence": "good", "has_data": True},
            {"criterion": "battery", "label": "Battery", "weight": 8, "score": 4, "evidence": "[NO DATA]", "has_data": False},
        ]},
    ]


_RUBRIC = {"weighted_criteria": [
    {"name": "camera", "label": "Camera", "weight": 9},
    {"name": "display", "label": "Display", "weight": 7},
    {"name": "water", "label": "Water", "weight": 6},
    {"name": "battery", "label": "Battery", "weight": 8},
]}


def test_identify_gaps_picks_highest_weight_nodata():
    gaps = ee.identify_gaps(_scored(), _RUBRIC)
    assert set(gaps["iQOO Z9x"][0].keys()) == {"criterion", "label", "weight"}
    # display (7) before water (6)
    assert [g["criterion"] for g in gaps["iQOO Z9x"]] == ["display", "water"]
    assert [g["criterion"] for g in gaps["Moto Edge 60"]] == ["battery"]


def test_patch_only_fills_asked_gaps(monkeypatch):
    scored = _scored()
    gaps = ee.identify_gaps(scored, _RUBRIC)
    extracted = [
        {"product": "iQOO Z9x", "criterion": "display", "score": 7, "evidence": "AMOLED 120Hz", "source": "gsmarena.com"},
        {"product": "iQOO Z9x", "criterion": "camera",  "score": 2, "evidence": "tries to overwrite real data", "source": "x.com"},
        {"product": "Ghost",    "criterion": "display", "score": 9, "evidence": "hallucinated product", "source": "y.com"},
    ]
    n = ee._patch_scores(scored, extracted, gaps)
    assert n == 1, "only the display gap should be filled"
    disp = next(s for s in scored[0]["scores"] if s["criterion"] == "display")
    assert disp["has_data"] is True and disp["score"] == 7.0 and "gsmarena.com" in disp["evidence"]
    # real camera data must NOT be overwritten
    cam = next(s for s in scored[0]["scores"] if s["criterion"] == "camera")
    assert cam["score"] == 6 and cam["has_data"] is True


def test_enrich_disabled_returns_unchanged(monkeypatch):
    monkeypatch.setattr(ee, "ENABLE_TARGETED_FETCH", False)
    scored = _scored()
    assert ee.enrich_scores(scored, _RUBRIC, "india") is scored


def test_enrich_no_serper_returns_unchanged(monkeypatch):
    monkeypatch.setattr(ee, "ENABLE_TARGETED_FETCH", True)
    monkeypatch.setattr(ee.google_search, "is_configured", lambda: False)
    scored = _scored()
    assert ee.enrich_scores(scored, _RUBRIC, "india") is scored


def test_enrich_end_to_end_fills_and_refinalizes(monkeypatch):
    monkeypatch.setattr(ee, "ENABLE_TARGETED_FETCH", True)
    monkeypatch.setattr(ee.google_search, "is_configured", lambda: True)
    # Stub Serper: one snippet bundle per product
    monkeypatch.setattr(ee.google_search, "search",
                        lambda q, num=6: [{"title": "Review", "link": "https://gsmarena.com/x", "snippet": "AMOLED 120Hz, IP54, 6000mAh"}])
    # Stub the extraction LLM
    monkeypatch.setattr(ee, "run_agent", lambda *a, **k: '{"results":['
        '{"product":"iQOO Z9x","criterion":"display","score":8,"evidence":"AMOLED 120Hz","source":"gsmarena.com"},'
        '{"product":"iQOO Z9x","criterion":"water","score":5,"evidence":"IP54","source":"gsmarena.com"},'
        '{"product":"Moto Edge 60","criterion":"battery","score":9,"evidence":"6000mAh","source":"gsmarena.com"}'
        ']}')
    scored = _scored()
    out = ee.enrich_scores(scored, _RUBRIC, "india")
    # All three gaps now have real data + confidence/coverage attached by _finalize_scoring
    iq = next(p for p in out if p["name"] == "iQOO Z9x")
    assert all(s["has_data"] for s in iq["scores"]), "all of iQOO's gaps filled with real data"
    assert "data_coverage" in iq and "confidence" in iq
    assert iq["data_coverage"] >= 0.7 and iq["confidence"] == "high"
    # the previously-missing display gap now carries the real value + source
    disp = next(s for s in iq["scores"] if s["criterion"] == "display")
    assert disp["score"] == 8.0 and "gsmarena.com" in disp["evidence"]


def test_deep_read_appends_full_page(monkeypatch):
    """With deep fetch on, the top result's full page is read (Jina) and bundled into evidence."""
    monkeypatch.setattr(ee, "ENABLE_DEEP_FETCH", True)
    monkeypatch.setattr(ee.google_search, "search",
                        lambda q, num=6: [{"title": "Spec", "link": "https://gsmarena.com/x", "snippet": "short"}])
    import review_fetch
    monkeypatch.setattr(review_fetch, "_fetch_via_jina",
                        lambda url: "FULL PAGE BODY: display 1300 nits, AnTuTu 720000, IP54")
    # bust any cached deepread for determinism
    import cache
    cache.set("enrich_deepread", "deepread|https://gsmarena.com/x", None)
    name, text = ee._fetch_product_evidence("iQOO Z9x", "india")
    assert "FULL PAGE" in text and "1300 nits" in text, "full-page content must be appended"


def test_deep_read_falls_back_on_failure(monkeypatch):
    monkeypatch.setattr(ee, "ENABLE_DEEP_FETCH", True)
    monkeypatch.setattr(ee.google_search, "search",
                        lambda q, num=6: [{"title": "Spec", "link": "https://x.com/y", "snippet": "snip"}])
    import review_fetch
    def _boom(url):
        raise RuntimeError("jina down")
    monkeypatch.setattr(review_fetch, "_fetch_via_jina", _boom)
    import cache
    cache.set("enrich_deepread", "deepread|https://x.com/y", None)
    name, text = ee._fetch_product_evidence("Some Phone", "india")
    # snippet still present, no crash
    assert "snip" in text


def test_enrich_llm_failure_returns_unchanged(monkeypatch):
    monkeypatch.setattr(ee, "ENABLE_TARGETED_FETCH", True)
    monkeypatch.setattr(ee.google_search, "is_configured", lambda: True)
    monkeypatch.setattr(ee.google_search, "search",
                        lambda q, num=6: [{"title": "R", "link": "https://x.com", "snippet": "stuff"}])
    def _boom(*a, **k):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(ee, "run_agent", _boom)
    scored = _scored()
    # Extraction fails → no patches → original list returned (never raises)
    assert ee.enrich_scores(scored, _RUBRIC, "india") is scored
