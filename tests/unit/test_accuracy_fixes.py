"""
Tests for the 4 critical accuracy fixes:
  Fix 1: Hallucination filter (products with no text corroboration dropped)
  Fix 2: Hard constraint pre-filter (violating products excluded before scoring)
  Fix 3: Memory category bleed prevention (broad hints narrowed to specific category)
  Fix 4: Cache key includes memory fingerprint (stale cache busted on signal change)
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))


# ---------------------------------------------------------------------------
# Fix 1: Hallucination filter
# ---------------------------------------------------------------------------

class TestHallucinationFilter:
    """
    The hallucination filter lives in pipeline_runner._execute_pipeline.
    We test the filter logic in isolation by replicating its predicate.
    """

    @staticmethod
    def _apply_filter(products: list[dict]) -> tuple[list[dict], int]:
        kept = [p for p in products if p.get("mention_count", 0) > 0 or p.get("sources")]
        dropped = len(products) - len(kept)
        return kept, dropped

    def test_zero_mentions_no_sources_dropped(self):
        products = [{"name": "Ghost Product", "mention_count": 0, "sources": []}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 1
        assert len(kept) == 0

    def test_zero_mentions_no_sources_key_missing_dropped(self):
        # Neither key present — should also be dropped
        products = [{"name": "Phantom", "signal_strength": "low"}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 1

    def test_zero_mentions_with_sources_kept(self):
        # Review-site-only product: no Reddit mention but has a source URL
        products = [{"name": "Review-Only Product", "mention_count": 0,
                     "sources": ["https://rtings.com/..."]}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 0
        assert len(kept) == 1

    def test_positive_mention_count_kept(self):
        products = [{"name": "Real Product", "mention_count": 5, "sources": []}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 0
        assert kept[0]["name"] == "Real Product"

    def test_mixed_list_correct_split(self):
        products = [
            {"name": "A", "mention_count": 3, "sources": ["r/tech"]},
            {"name": "B", "mention_count": 0, "sources": []},  # hallucinated
            {"name": "C", "mention_count": 0, "sources": ["https://review.com"]},
            {"name": "D", "mention_count": 0, "sources": None},  # hallucinated
            {"name": "E", "mention_count": 1},
        ]
        kept, dropped = self._apply_filter(products)
        assert dropped == 2
        assert {p["name"] for p in kept} == {"A", "C", "E"}

    def test_empty_list_returns_empty(self):
        kept, dropped = self._apply_filter([])
        assert kept == []
        assert dropped == 0

    def test_all_valid_none_dropped(self):
        products = [{"name": f"P{i}", "mention_count": i + 1} for i in range(5)]
        kept, dropped = self._apply_filter(products)
        assert dropped == 0
        assert len(kept) == 5

    def test_sources_none_treated_as_empty(self):
        products = [{"name": "X", "mention_count": 0, "sources": None}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 1

    def test_sources_nonempty_string_list_kept(self):
        products = [{"name": "Y", "mention_count": 0,
                     "sources": ["r/audiophile", "r/budgetaudio"]}]
        kept, dropped = self._apply_filter(products)
        assert dropped == 0


# ---------------------------------------------------------------------------
# Fix 2: Hard constraint pre-filter (filter_constraint_violators)
# ---------------------------------------------------------------------------

from scorer import filter_constraint_violators  # noqa: E402


def _make_products(*names: str) -> list[dict]:
    return [{"name": n, "mention_count": 1, "sources": ["r/test"]} for n in names]


class TestConstraintFilterNoConstraints:
    def test_no_user_intent_returns_all(self):
        products = _make_products("Alpha", "Beta")
        kept, violated = filter_constraint_violators(products, None, "")
        assert kept == products
        assert violated == []

    def test_empty_intent_dict_returns_all(self):
        products = _make_products("Alpha", "Beta")
        kept, violated = filter_constraint_violators(products, {}, "")
        assert kept == products
        assert violated == []

    def test_no_constraints_no_exclusions_returns_all(self):
        products = _make_products("Alpha", "Beta")
        intent = {"hard_constraints": [], "exclusions": [], "budget": "under 5000"}
        kept, violated = filter_constraint_violators(products, intent, "")
        assert kept == products
        assert violated == []


class TestConstraintFilterLLMBehavior:
    def _mock_run_agent(self, compliant_map: dict[str, bool]):
        """Build mock LLM response where each product maps to compliant bool."""
        results = [
            {"name": name, "compliant": compliant, "reason": "" if compliant else "Violates constraint"}
            for name, compliant in compliant_map.items()
        ]
        return json.dumps({"results": results})

    def test_all_compliant_none_excluded(self):
        products = _make_products("Wireless A", "Wireless B")
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        response = self._mock_run_agent({"Wireless A": True, "Wireless B": True})
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert len(kept) == 2
        assert len(violated) == 0

    def test_one_violation_excluded(self):
        products = _make_products("Wired Headset", "Wireless Buds")
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        response = self._mock_run_agent({"Wired Headset": False, "Wireless Buds": True})
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert len(kept) == 1
        assert kept[0]["name"] == "Wireless Buds"
        assert len(violated) == 1
        assert violated[0]["name"] == "Wired Headset"
        assert "constraint_violation_reason" in violated[0]

    def test_all_violated_empty_main_results(self):
        products = _make_products("In-Ear A", "In-Ear B")
        intent = {"hard_constraints": [], "exclusions": ["in-ear"]}
        response = self._mock_run_agent({"In-Ear A": False, "In-Ear B": False})
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert kept == []
        assert len(violated) == 2

    def test_product_missing_from_llm_response_defaults_to_compliant(self):
        # LLM only returns one product — the other defaults to kept
        products = _make_products("Known", "Unknown")
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        response = self._mock_run_agent({"Known": True})  # Unknown not in response
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert {p["name"] for p in kept} == {"Known", "Unknown"}
        assert violated == []

    def test_llm_failure_returns_all_compliant(self):
        products = _make_products("A", "B", "C")
        intent = {"hard_constraints": ["must have ANC"], "exclusions": []}
        with patch("scorer.run_agent", side_effect=RuntimeError("LLM down")):
            kept, violated = filter_constraint_violators(products, intent, "")
        # Fail open — all products returned
        assert kept == products
        assert violated == []

    def test_malformed_json_from_llm_returns_all_compliant(self):
        products = _make_products("A", "B")
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        with patch("scorer.run_agent", return_value="not json at all !!!"):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert len(kept) == 2
        assert violated == []

    def test_violated_product_carries_reason(self):
        products = _make_products("Corded Mouse")
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        response = json.dumps({"results": [
            {"name": "Corded Mouse", "compliant": False, "reason": "Has a physical cable"}
        ]})
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators(products, intent, "")
        assert violated[0]["constraint_violation_reason"] == "Has a physical cable"

    def test_empty_product_list_returns_empty_both(self):
        intent = {"hard_constraints": ["must be wireless"], "exclusions": []}
        response = json.dumps({"results": []})
        with patch("scorer.run_agent", return_value=response):
            kept, violated = filter_constraint_violators([], intent, "")
        assert kept == []
        assert violated == []


# ---------------------------------------------------------------------------
# Fix 3: Memory category bleed prevention
# ---------------------------------------------------------------------------

class TestMemoryCategoryBleed:
    """
    Test that extract_and_save_signals narrows broad category hints to the
    specific current category for product-attribute signals.
    """

    def _run_narrowing(self, signals: list[dict], category: str) -> list[dict]:
        """Apply the hint-narrowing logic in isolation."""
        import copy
        signals = copy.deepcopy(signals)
        _CROSS_CATEGORY_SAFE_TERMS = frozenset({
            "brand", "budget", "price", "warranty", "durability", "build quality",
            "material", "design", "reliability", "longevity", "value", "aesthetic",
            "weight", "portability", "colour", "color",
        })
        if "/" in category:
            _top_level = category.split("/")[0].lower()
            for _sig in signals:
                _hint = _sig.get("category_hint", "any")
                if _hint in ("any", category):
                    continue
                if _hint == _top_level:
                    _sig_lower = _sig.get("text", "").lower()
                    _is_safe = any(term in _sig_lower for term in _CROSS_CATEGORY_SAFE_TERMS)
                    if not _is_safe:
                        _sig["category_hint"] = category
        return signals

    def test_audio_signal_narrowed_from_electronics_to_earbuds(self):
        signals = [{"category_hint": "electronics", "text": "Prefers bass-heavy sound signature",
                    "type": "preference", "strength": "moderate"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        assert result[0]["category_hint"] == "electronics/earbuds"

    def test_anc_signal_narrowed(self):
        signals = [{"category_hint": "electronics",
                    "text": "Needs strong active noise cancellation for commute",
                    "type": "preference", "strength": "strong"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        assert result[0]["category_hint"] == "electronics/earbuds"

    def test_brand_signal_not_narrowed(self):
        signals = [{"category_hint": "electronics", "text": "Prefers Sony brand over others",
                    "type": "preference", "strength": "moderate"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        # "brand" is in safe terms — should NOT be narrowed
        assert result[0]["category_hint"] == "electronics"

    def test_price_signal_not_narrowed(self):
        signals = [{"category_hint": "electronics", "text": "Strict budget — price sensitive",
                    "type": "preference", "strength": "strong"}]
        result = self._run_narrowing(signals, "electronics/headphones")
        assert result[0]["category_hint"] == "electronics"

    def test_any_hint_never_narrowed(self):
        signals = [{"category_hint": "any", "text": "Has sensitive skin",
                    "type": "preference", "strength": "strong"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        assert result[0]["category_hint"] == "any"

    def test_already_specific_hint_not_changed(self):
        signals = [{"category_hint": "electronics/earbuds",
                    "text": "Prefers in-canal fit",
                    "type": "preference", "strength": "moderate"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        assert result[0]["category_hint"] == "electronics/earbuds"

    def test_non_electronics_top_level_not_affected(self):
        # Hint "beauty" doesn't match "electronics" top-level, no change
        signals = [{"category_hint": "beauty", "text": "Prefers fragrance-free products",
                    "type": "preference", "strength": "moderate"}]
        result = self._run_narrowing(signals, "electronics/earbuds")
        assert result[0]["category_hint"] == "beauty"

    def test_no_slash_in_category_no_narrowing(self):
        # If current category has no slash, skip narrowing entirely
        signals = [{"category_hint": "electronics", "text": "Prefers bass-heavy sound",
                    "type": "preference", "strength": "weak"}]
        result = self._run_narrowing(signals, "electronics")
        assert result[0]["category_hint"] == "electronics"

    def test_durability_signal_not_narrowed(self):
        signals = [{"category_hint": "electronics",
                    "text": "Cares a lot about durability and build quality",
                    "type": "preference", "strength": "strong"}]
        result = self._run_narrowing(signals, "electronics/keyboards")
        # "durability" + "build quality" both in safe terms
        assert result[0]["category_hint"] == "electronics"

    def test_multiple_signals_mixed_narrowing(self):
        signals = [
            {"category_hint": "electronics", "text": "Wants balanced frequency response",
             "type": "preference", "strength": "moderate"},
            {"category_hint": "electronics", "text": "Only buys Sony brand",
             "type": "preference", "strength": "strong"},
            {"category_hint": "any", "text": "Has flat feet",
             "type": "preference", "strength": "strong"},
        ]
        result = self._run_narrowing(signals, "electronics/headphones")
        assert result[0]["category_hint"] == "electronics/headphones"  # narrowed
        assert result[1]["category_hint"] == "electronics"              # safe (brand)
        assert result[2]["category_hint"] == "any"                      # never touched


# ---------------------------------------------------------------------------
# Fix 4: Cache key includes memory fingerprint
# ---------------------------------------------------------------------------

from api.pipeline_runner import _pipeline_cache_key  # noqa: E402


def _base_rubric():
    return {"weighted_criteria": [{"name": "sound_quality", "weight": 8}]}


def _base_profile(**kwargs):
    return {"interview": [{"question": "Budget?", "answer": "under 3000"}], **kwargs}


class TestCacheKeyMemoryFingerprint:
    def test_guest_user_no_memory_fingerprint(self):
        profile = _base_profile(user_id="default")
        key = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        assert isinstance(key, str) and len(key) == 32  # MD5 hex

    def test_legacy_user_no_memory_fingerprint(self):
        profile = _base_profile(user_id="__legacy__")
        key = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        assert isinstance(key, str) and len(key) == 32

    def test_auth_user_with_signals_differs_from_no_signals(self):
        profile = _base_profile(user_id="auth_abc123")
        no_signals = []
        one_signal = [{"type": "preference", "text": "Prefers bass", "strength": "moderate"}]

        with patch("memory.list_user_signals", return_value=no_signals):
            key_empty = _pipeline_cache_key(
                "best earbuds", "electronics/earbuds", _base_rubric(), profile
            )

        with patch("memory.list_user_signals", return_value=one_signal):
            key_signal = _pipeline_cache_key(
                "best earbuds", "electronics/earbuds", _base_rubric(), profile
            )

        assert key_empty != key_signal

    def test_same_signals_same_key(self):
        profile = _base_profile(user_id="auth_abc123")
        signals = [{"type": "preference", "text": "Prefers bass", "strength": "moderate"}]
        with patch("memory.list_user_signals", return_value=signals):
            k1 = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
            k2 = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        assert k1 == k2

    def test_different_signals_different_keys(self):
        profile = _base_profile(user_id="auth_xyz")
        signals_a = [{"type": "preference", "text": "Prefers bass", "strength": "moderate"}]
        signals_b = [{"type": "rejection",  "text": "Hates Apple", "strength": "strong"}]
        with patch("memory.list_user_signals", return_value=signals_a):
            ka = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        with patch("memory.list_user_signals", return_value=signals_b):
            kb = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        assert ka != kb

    def test_memory_lookup_failure_falls_back_gracefully(self):
        profile = _base_profile(user_id="auth_xyz")
        with patch("memory.list_user_signals", side_effect=Exception("DB down")):
            key = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        # Should still return a valid MD5 — no exception raised
        assert isinstance(key, str) and len(key) == 32

    def test_no_profile_no_crash(self):
        key = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), None)
        assert isinstance(key, str) and len(key) == 32

    def test_query_change_changes_key(self):
        profile = _base_profile(user_id="default")
        k1 = _pipeline_cache_key("best earbuds", "electronics/earbuds", _base_rubric(), profile)
        k2 = _pipeline_cache_key("best headphones", "electronics/earbuds", _base_rubric(), profile)
        assert k1 != k2

    def test_rubric_weight_change_changes_key(self):
        profile = _base_profile(user_id="default")
        rubric_a = {"weighted_criteria": [{"name": "sound_quality", "weight": 8}]}
        rubric_b = {"weighted_criteria": [{"name": "sound_quality", "weight": 5}]}
        k1 = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric_a, profile)
        k2 = _pipeline_cache_key("best earbuds", "electronics/earbuds", rubric_b, profile)
        assert k1 != k2
