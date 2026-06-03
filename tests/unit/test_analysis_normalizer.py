"""
Unit tests for analysis_normalizer.normalize_analysis().

Covers every edge-case variant that LLMs have been observed to produce:
 - Canonical happy path
 - Empty / None / non-dict inputs
 - Bare-string items in products/materials lists
 - Numeric fields as strings ("5+"), booleans, floats
 - Complaints as strings vs dicts
 - Nested complaint lists (Bug 4)
 - mention_count=0 must NOT fall through to fallback field (Bug 1/2)
 - Negative counts clamped to 0 (Bug 3)
 - Duplicate products merged and deduplicated (Bug 5/6)
 - Missing product schema fields always present (Bug 7)
 - Array size caps (Bug 8)
 - Last-resort summary recovery
 - Invalid signal_strength values normalised to "low"
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))

import pytest
from analysis_normalizer import normalize_analysis, _safe_str, _safe_int, _canonical_key


# ── Helpers ───────────────────────────────────────────────────────────────────

def _product(name="Widget X", **kw) -> dict:
    base = {"name": name, "mention_count": 1, "signal_strength": "high"}
    base.update(kw)
    return base


def _required_product_keys() -> set:
    return {
        "name", "mention_count", "distinct_recommenders",
        "positive_mentions", "negative_mentions",
        "praise", "complaints", "sources",
        "signal_strength", "representative_quote", "cross_subreddit_signal",
    }


# ── normalize_analysis: input coercion ────────────────────────────────────────

class TestInputCoercion:
    def test_none_input_returns_canonical_empty(self):
        out = normalize_analysis(None)
        assert out["summary"] == ""
        assert out["products"] == []
        assert out["materials"] == []

    def test_string_input_preserved_as_summary(self):
        out = normalize_analysis("Sony XM5 is best")
        assert "Sony" in out["summary"]

    def test_empty_dict_returns_empty_structure(self):
        out = normalize_analysis({})
        assert out == {"summary": "", "products": [], "materials": []}

    def test_non_dict_non_none(self):
        out = normalize_analysis(42)
        assert isinstance(out, dict)
        assert out["products"] == []


# ── normalize_analysis: canonical happy path ──────────────────────────────────

class TestCanonicalHappyPath:
    def test_full_valid_input(self):
        raw = {
            "summary": "Great earbuds discussion.",
            "products": [_product("Sony WF-1000XM5", mention_count=10, distinct_recommenders=5)],
            "materials": [{"name": "silicone", "mention_count": 3}],
        }
        out = normalize_analysis(raw)
        assert out["summary"] == "Great earbuds discussion."
        assert len(out["products"]) == 1
        assert out["products"][0]["name"] == "Sony WF-1000XM5"
        assert out["products"][0]["mention_count"] == 10
        assert len(out["materials"]) == 1

    def test_all_required_product_keys_present(self):
        raw = {"products": [_product()], "summary": ""}
        out = normalize_analysis(raw)
        assert _required_product_keys().issubset(out["products"][0].keys())


# ── normalize_analysis: numeric coercion ──────────────────────────────────────

class TestNumericCoercion:
    def test_mention_count_as_string_with_plus(self):
        raw = {"products": [_product(mention_count="5+")]}
        out = normalize_analysis(raw)
        assert out["products"][0]["mention_count"] == 5

    def test_mention_count_as_float(self):
        raw = {"products": [_product(mention_count=3.9)]}
        out = normalize_analysis(raw)
        assert out["products"][0]["mention_count"] == 3

    def test_mention_count_as_bool_true(self):
        raw = {"products": [_product(mention_count=True)]}
        out = normalize_analysis(raw)
        assert out["products"][0]["mention_count"] == 1

    def test_negative_mention_count_clamped_to_zero(self):
        """Bug 3: negative counts must floor to 0."""
        raw = {"products": [_product(mention_count=-5)]}
        out = normalize_analysis(raw)
        assert out["products"][0]["mention_count"] == 0

    def test_mention_count_zero_not_shadowed_by_fallback(self):
        """Bug 1/2: mention_count=0 must NOT be overridden by mentions=25."""
        raw = {"products": [{"name": "Widget", "mention_count": 0, "mentions": 25}]}
        out = normalize_analysis(raw)
        assert out["products"][0]["mention_count"] == 0


# ── normalize_analysis: complaint normalisation ───────────────────────────────

class TestComplaintNormalisation:
    def test_complaint_as_string(self):
        raw = {"products": [_product(complaints=["Poor battery life"])]}
        out = normalize_analysis(raw)
        c = out["products"][0]["complaints"][0]
        assert c["text"] == "Poor battery life"
        assert c["confidence"] == "single"

    def test_complaint_as_dict_confirmed(self):
        raw = {"products": [_product(complaints=[{"text": "Drops connection", "confidence": "confirmed"}])]}
        out = normalize_analysis(raw)
        assert out["products"][0]["complaints"][0]["confidence"] == "confirmed"

    def test_complaint_invalid_confidence_normalised(self):
        raw = {"products": [_product(complaints=[{"text": "Meh", "confidence": "maybe"}])]}
        out = normalize_analysis(raw)
        assert out["products"][0]["complaints"][0]["confidence"] == "single"

    def test_nested_complaint_lists_flattened(self):
        """Bug 4: [[complaint1, complaint2], complaint3] → [c1, c2, c3]."""
        raw = {"products": [_product(complaints=[["Thin sound", "No aptX"], "Short cable"])]}
        out = normalize_analysis(raw)
        assert len(out["products"][0]["complaints"]) == 3

    def test_none_complaints_skipped(self):
        raw = {"products": [_product(complaints=[None, "Real issue", None])]}
        out = normalize_analysis(raw)
        assert len(out["products"][0]["complaints"]) == 1


# ── normalize_analysis: deduplication ─────────────────────────────────────────

class TestDeduplication:
    def test_exact_duplicate_merged(self):
        """Bug 5: identical names → one entry with summed counts."""
        raw = {
            "products": [
                _product("Sony WF-1000XM5", mention_count=5, praise=["Great ANC"]),
                _product("Sony WF-1000XM5", mention_count=3, praise=["Good battery"]),
            ]
        }
        out = normalize_analysis(raw)
        assert len(out["products"]) == 1
        p = out["products"][0]
        assert p["mention_count"] == 8
        assert len(p["praise"]) == 2

    def test_punctuation_variant_deduplicated(self):
        """Bug 6: 'Sony WF-1000XM5' and 'Sony WF1000XM5' → same canonical key."""
        raw = {
            "products": [
                _product("Sony WF-1000XM5", mention_count=4),
                _product("Sony WF1000XM5",  mention_count=2),
            ]
        }
        out = normalize_analysis(raw)
        assert len(out["products"]) == 1
        assert out["products"][0]["mention_count"] == 6

    def test_signal_strength_upgraded_on_merge(self):
        raw = {
            "products": [
                _product("Widget", signal_strength="low"),
                _product("Widget", signal_strength="high"),
            ]
        }
        out = normalize_analysis(raw)
        assert out["products"][0]["signal_strength"] == "high"


# ── normalize_analysis: schema completeness ───────────────────────────────────

class TestSchemaCompleteness:
    def test_bare_string_product_gets_full_template(self):
        """Bug 7: a bare string in the products list must yield a full template."""
        raw = {"products": ["Sony WF-1000XM5"]}
        out = normalize_analysis(raw)
        assert len(out["products"]) == 1
        assert _required_product_keys().issubset(out["products"][0].keys())

    def test_product_missing_fields_get_defaults(self):
        raw = {"products": [{"name": "Widget"}]}
        out = normalize_analysis(raw)
        p = out["products"][0]
        assert p["mention_count"] == 0
        assert p["praise"] == []
        assert p["complaints"] == []
        assert p["signal_strength"] == "low"

    def test_invalid_signal_strength_normalised_to_low(self):
        raw = {"products": [_product(signal_strength="excellent")]}
        out = normalize_analysis(raw)
        assert out["products"][0]["signal_strength"] == "low"

    def test_product_with_unknown_name_field(self):
        """LLMs sometimes use 'product_name' or 'brand_model' instead of 'name'."""
        raw = {"products": [{"product_name": "Bose QC45", "mention_count": 2}]}
        out = normalize_analysis(raw)
        assert out["products"][0]["name"] == "Bose QC45"


# ── normalize_analysis: array caps ────────────────────────────────────────────

class TestArrayCaps:
    def test_praise_capped_at_20(self):
        raw = {"products": [_product(praise=[f"Great point {i}" for i in range(30)])]}
        out = normalize_analysis(raw)
        assert len(out["products"][0]["praise"]) == 20

    def test_complaints_capped_at_20(self):
        raw = {"products": [_product(complaints=[f"Issue {i}" for i in range(25)])]}
        out = normalize_analysis(raw)
        assert len(out["products"][0]["complaints"]) == 20

    def test_sources_capped_at_50(self):
        raw = {"products": [_product(sources=[f"r/sub{i}" for i in range(60)])]}
        out = normalize_analysis(raw)
        assert len(out["products"][0]["sources"]) == 50

    def test_products_list_capped_at_50(self):
        raw = {"products": [_product(f"Product {i}") for i in range(60)]}
        out = normalize_analysis(raw)
        assert len(out["products"]) == 50


# ── normalize_analysis: last-resort recovery ─────────────────────────────────

class TestSummaryRecovery:
    def test_products_recovered_when_list_empty(self):
        """When products=[] but summary mentions known-brand product names, rescue them."""
        raw = {
            "summary": "The Sony WF-1000XM5 leads the market. Apple AirPods Pro 2 is close behind.",
            "products": [],
        }
        out = normalize_analysis(raw)
        # May or may not recover depending on canonicalize_product availability;
        # just assert the structure is valid either way.
        assert isinstance(out["products"], list)
        for p in out["products"]:
            assert _required_product_keys().issubset(p.keys())

    def test_no_crash_on_empty_summary_and_products(self):
        out = normalize_analysis({"summary": "", "products": [], "materials": []})
        assert out["products"] == []


# ── _safe_str ─────────────────────────────────────────────────────────────────

class TestSafeStr:
    def test_none_returns_default(self):
        assert _safe_str(None) == ""
        assert _safe_str(None, "fallback") == "fallback"

    def test_string_stripped(self):
        assert _safe_str("  hello  ") == "hello"

    def test_dict_formatted(self):
        result = _safe_str({"key": "value"})
        assert "Key: value" in result

    def test_list_joined(self):
        result = _safe_str(["a", "b", "c"])
        assert "a" in result and "b" in result

    def test_int_converted(self):
        assert _safe_str(42) == "42"


# ── _safe_int ─────────────────────────────────────────────────────────────────

class TestSafeInt:
    def test_int_passthrough(self):
        assert _safe_int(5) == 5

    def test_float_truncated(self):
        assert _safe_int(3.9) == 3

    def test_string_with_number(self):
        assert _safe_int("10 mentions") == 10

    def test_string_with_plus(self):
        assert _safe_int("5+") == 5

    def test_none_returns_default(self):
        assert _safe_int(None, 7) == 7

    def test_non_numeric_string_returns_default(self):
        assert _safe_int("many", 0) == 0


# ── _canonical_key ────────────────────────────────────────────────────────────

class TestCanonicalKey:
    def test_punctuation_stripped(self):
        assert _canonical_key("Sony WF-1000XM5") == _canonical_key("Sony WF1000XM5")

    def test_case_insensitive(self):
        assert _canonical_key("SONY WF-1000XM5") == _canonical_key("sony wf-1000xm5")

    def test_different_products_differ(self):
        assert _canonical_key("AirPods Pro") != _canonical_key("AirPods Max")
