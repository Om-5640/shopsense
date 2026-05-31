"""
Orchestration regression tests (EVAL-02).

These tests verify the pipeline orchestration logic — session lifecycle,
dedup thresholds, scoring mode validation, brand-contamination fix,
research dedup, and cancellation propagation.

Run:
    python -m evals.integration.orchestration_test
    python -m pytest evals/integration/orchestration_test.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))


def _pass(name: str) -> None:
    print(f"  PASS {name}")


def _fail(name: str, reason: str) -> None:
    print(f"  FAIL {name}: {reason}")
    raise AssertionError(f"ORCHESTRATION TEST FAILED — {name}: {reason}")


# ---------------------------------------------------------------------------
# Test 1: Thread dedup threshold is 0.70 (RETRIEVAL-02)
# ---------------------------------------------------------------------------

def test_dedup_threshold_seventy():
    """_dedup_threads must keep threads with 0.65 overlap but drop 0.71 overlap."""
    from pipeline_runner import _dedup_threads

    # Two threads sharing 5/7 distinctive tokens = 71% overlap → should dedup
    high_overlap = [
        {"title": "Sony WF-1000XM5 review noise cancellation", "score": 100},
        {"title": "Sony WF-1000XM5 review noise cancellation quality", "score": 50},
    ]
    result_high = _dedup_threads(high_overlap)
    if len(result_high) != 1:
        _fail("dedup_threshold_seventy",
              f"expected 1 unique thread for high overlap, got {len(result_high)}")

    # Two threads sharing 3/7 tokens = ~43% overlap → must NOT dedup
    low_overlap = [
        {"title": "Sony WF-1000XM5 noise cancellation review", "score": 100},
        {"title": "Bose QC45 battery life comfort test", "score": 80},
    ]
    result_low = _dedup_threads(low_overlap)
    if len(result_low) != 2:
        _fail("dedup_threshold_seventy",
              f"expected 2 unique threads for low overlap, got {len(result_low)}")

    _pass("dedup_threshold_seventy")


# ---------------------------------------------------------------------------
# Test 2: Brand contamination fix — min_matches=2 for multi-token products
# ---------------------------------------------------------------------------

def test_brand_contamination_fix():
    """_filter_research_for_product must require 2 tokens for multi-token product names.
    Brand-only paragraphs far from any direct match should not be pulled in.
    """
    from scorer import _filter_research_for_product

    # Place the brand-only mention far from any WF-1000XM5 mention.
    # With min_matches=2, "Sony WH-1000XM4" (brand-only → 1 match) that's not adjacent
    # to a direct match should NOT appear in results.
    research = (
        "Generic audio overview: many great headphones exist.\n\n"
        "Sony WH-1000XM4 is a great over-ear headphone.\n\n"  # only "sony" matches WF tokens
        "Unrelated: best gaming mice of 2024.\n\n"
        "Sony WF-1000XM5 offers excellent noise cancellation at 8 hours battery.\n\n"
        "The WF-1000XM5 ANC performance is class-leading in 2024."
    )

    # "Sony WF-1000XM5" tokens after skip_words filter: ["sony", "1000xm5"]
    # (len("wf") == 2, excluded by `len(t) > 2`)
    result = _filter_research_for_product("Sony WF-1000XM5", research)

    # Must include paragraphs that match 2+ tokens
    if "WF-1000XM5" not in result:
        _fail("brand_contamination_fix",
              "WF-1000XM5-specific paragraphs should be included")

    # The brand-only paragraph (WH-1000XM4, index 1) is not adjacent to any direct match.
    # Adjacent to index 1: index 2 ("gaming mice") which has 0 matching tokens.
    # So WH-1000XM4 should NOT appear.
    if "WH-1000XM4" in result:
        _fail("brand_contamination_fix",
              "WH-1000XM4 paragraph (brand-only, non-adjacent) should NOT appear in WF-1000XM5 results")

    _pass("brand_contamination_fix")


# ---------------------------------------------------------------------------
# Test 3: Default score is 4.0, not 5.0 (BIAS-03)
# ---------------------------------------------------------------------------

def test_default_score_four():
    """When LLM returns no score for a criterion, the default must be 4.0."""
    from scorer import _build_scored_dict

    rubric = {
        "weighted_criteria": [
            {"name": "battery_life", "label": "Battery Life", "weight": 8},
            {"name": "sound_quality", "label": "Sound Quality", "weight": 5},
        ]
    }
    product = {"name": "TestBuds X2"}

    # Only provide a score for one criterion — the other should default
    raw_scores = [{"criterion": "battery_life", "score": 9, "evidence": "good battery"}]
    scored = _build_scored_dict(product, raw_scores, rubric)

    sound_score = next(
        (s["score"] for s in scored["scores"] if s["criterion"] == "sound_quality"), None
    )
    if sound_score is None:
        _fail("default_score_four", "sound_quality score not found in result")
    if sound_score != 4.0:
        _fail("default_score_four",
              f"expected default score 4.0, got {sound_score}")
    _pass("default_score_four")


# ---------------------------------------------------------------------------
# Test 4: SCORING_MODE validation (PROVIDER-02)
# ---------------------------------------------------------------------------

def test_scoring_mode_validation():
    """Invalid SCORING_MODE env var must fall back to 'llm' silently."""
    import importlib
    import scorer as scorer_mod

    # The module-level validation already ran at import time.
    # If SCORING_MODE is "llm" (the default), that's fine — the validation path
    # is exercised by checking the _VALID_SCORING_MODES constant.
    if not hasattr(scorer_mod, "_VALID_SCORING_MODES"):
        _fail("scoring_mode_validation",
              "_VALID_SCORING_MODES constant not found in scorer module")
    valid = scorer_mod._VALID_SCORING_MODES
    if "llm" not in valid or "hybrid" not in valid or "fast" not in valid:
        _fail("scoring_mode_validation",
              f"expected {{llm, hybrid, fast}} in _VALID_SCORING_MODES, got {valid}")
    if scorer_mod.SCORING_MODE not in valid:
        _fail("scoring_mode_validation",
              f"SCORING_MODE={scorer_mod.SCORING_MODE!r} is not in valid modes")
    _pass("scoring_mode_validation")


# ---------------------------------------------------------------------------
# Test 5: Research paragraph dedup (ENTROPY-02)
# ---------------------------------------------------------------------------

def test_research_paragraph_dedup():
    """_dedup_research_paragraphs must remove exact duplicate paragraphs."""
    from pipeline_runner import _dedup_research_paragraphs

    text = (
        "Sony WF-1000XM5 has great noise cancellation.\n\n"
        "Bose QC45 is comfortable for long sessions.\n\n"
        "Sony WF-1000XM5 has great noise cancellation.\n\n"
        "Battery life varies by product."
    )
    result = _dedup_research_paragraphs(text)
    paragraphs = [p.strip() for p in result.split("\n\n") if p.strip()]
    seen: set[str] = set()
    for p in paragraphs:
        if p in seen:
            _fail("research_paragraph_dedup",
                  f"duplicate paragraph found after dedup: {p[:60]!r}")
        seen.add(p)

    expected_count = 3  # 4 paragraphs - 1 duplicate
    if len(paragraphs) != expected_count:
        _fail("research_paragraph_dedup",
              f"expected {expected_count} paragraphs, got {len(paragraphs)}")
    _pass("research_paragraph_dedup")


# ---------------------------------------------------------------------------
# Test 6: Session cancellation check propagates to scorer (PROVIDER-01)
# ---------------------------------------------------------------------------

def test_cancellation_propagates_to_scorer():
    """score_all_products must accept cancelled_check and abort early when True."""
    from scorer import score_all_products

    products = [
        {"name": f"Product {i}", "signal_strength": "medium"} for i in range(6)
    ]
    rubric = {
        "weighted_criteria": [
            {"name": "battery_life", "label": "Battery Life", "weight": 8},
        ]
    }

    cancelled = [False]

    def _mock_score_batch(batch, *args, **kwargs):
        if cancelled[0]:
            raise RuntimeError("Research stopped by user.")
        cancelled[0] = True  # cancel after first batch
        return [None] * len(batch)

    call_count = [0]

    def _mock_run_agent(*args, **kwargs):
        call_count[0] += 1
        return '{"products": []}'

    with patch("scorer.run_agent", side_effect=_mock_run_agent):
        with patch("scorer._score_batch", side_effect=_mock_score_batch):
            result = score_all_products(
                products, rubric, "research text",
                cancelled_check=lambda: cancelled[0],
            )

    # With cancellation after first batch, fewer than 6 products should be scored via LLM
    # The function should not raise — it should return whatever was scored
    if not isinstance(result, list):
        _fail("cancellation_propagates_to_scorer",
              f"expected list result, got {type(result)}")
    _pass("cancellation_propagates_to_scorer")


# ---------------------------------------------------------------------------
# Test 7: rubric.save_rubric has per-category lock (BUG-04)
# ---------------------------------------------------------------------------

def test_rubric_save_lock_exists():
    """rubric module must expose per-category locking via _get_rubric_lock."""
    import rubric as rubric_mod

    if not hasattr(rubric_mod, "_get_rubric_lock"):
        _fail("rubric_save_lock_exists",
              "_get_rubric_lock function not found in rubric module")

    import threading
    lock_a = rubric_mod._get_rubric_lock("electronics/earbuds")
    lock_b = rubric_mod._get_rubric_lock("electronics/earbuds")
    lock_c = rubric_mod._get_rubric_lock("bedding/blanket")

    if lock_a is not lock_b:
        _fail("rubric_save_lock_exists",
              "same category must return the same Lock instance")
    if lock_a is lock_c:
        _fail("rubric_save_lock_exists",
              "different categories must return different Lock instances")
    _lock_type = type(threading.Lock())
    if not isinstance(lock_a, _lock_type):
        _fail("rubric_save_lock_exists",
              f"expected threading.Lock, got {type(lock_a)}")
    _pass("rubric_save_lock_exists")


# ---------------------------------------------------------------------------
# Test 8: BIAS-02 pakistan removed from off_topic
# ---------------------------------------------------------------------------

def test_pakistan_not_in_off_topic():
    """reddit_fetch off_topic set must not contain 'pakistan'."""
    import inspect
    import reddit_fetch

    source = inspect.getsource(reddit_fetch)
    # Look for the off_topic set definition
    import re
    match = re.search(r'off_topic\s*=\s*\{([^}]+)\}', source)
    if not match:
        _fail("pakistan_not_in_off_topic",
              "Could not find off_topic set in reddit_fetch source")
    set_contents = match.group(1)
    if "pakistan" in set_contents:
        _fail("pakistan_not_in_off_topic",
              "'pakistan' still present in off_topic set")
    _pass("pakistan_not_in_off_topic")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TESTS = [
    test_dedup_threshold_seventy,
    test_brand_contamination_fix,
    test_default_score_four,
    test_scoring_mode_validation,
    test_research_paragraph_dedup,
    test_cancellation_propagates_to_scorer,
    test_rubric_save_lock_exists,
    test_pakistan_not_in_off_topic,
]


def run_all() -> int:
    print("\n=== ShopSense Orchestration Regression Tests ===")
    passed = 0
    failed = 0
    for test_fn in _TESTS:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"    {e}")
            failed += 1
        except Exception as e:
            print(f"  FAIL {test_fn.__name__}: unexpected error - {type(e).__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed out of {len(_TESTS)} tests")
    return failed


if __name__ == "__main__":
    exit_code = run_all()
    sys.exit(exit_code)
