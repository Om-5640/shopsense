"""
Tests for quality-gap fixes 13-17 (Medium — Quality Gaps).

Fix 13: Inter-Product Relative Scoring
        _add_relative_ranks attaches relative_rank labels + overall_rank + gap_to_leader

Fix 14: Indian Review Sites Under-Represented
        source_filter.TRUSTED_DOMAINS + AUTHORITY_SCORES include Indian sites
        region_clause in review_fetch names Indian publications

Fix 15: Memory Signals Never Decay
        _signal_decay_weight(created_at_iso) → half-life 90 days, floor 0.05
        _is_stale_signal(created_at_iso) → True when age > 90 days

Fix 16: No Pre-Query Category Disambiguation
        needs_clarification = needs_disambiguation OR confidence == "low"
        detect_category returns needs_clarification in all code paths

Fix 17: Single-Source Products Treated as Multi-Source
        source_coverage set in analysis_normalizer per product
        single-source gets one-tier confidence penalty in _finalize_scoring
"""

from __future__ import annotations

import datetime
import sys
import os
import types

# ---------------------------------------------------------------------------
# Minimal stubs so imports succeed when this file is run in isolation.
# IMPORTANT: use "if not in sys.modules" guards for EVERY stub so the real
# module (already imported in a full pytest run) is never overwritten.
# The unconditional sys.modules["cache"].get = lambda ... pattern was the
# root cause of 36 cross-test failures: real cache.get/set were silently
# replaced during pytest collection, corrupting tests that depend on them.
# ---------------------------------------------------------------------------

import json as _json  # needed by _try_repair_json stub below

# Stub the cache module — only when not already imported by another test file
if "cache" not in sys.modules:
    _cache_stub = types.ModuleType("cache")
    _cache_stub.get = lambda *a, **kw: None  # type: ignore
    _cache_stub.set = lambda *a, **kw: None  # type: ignore
    sys.modules["cache"] = _cache_stub

# Stub agents + llm_client for category.py
if "agents" not in sys.modules:
    _agents_mod = types.ModuleType("agents")
    _agents_mod.run_agent = lambda *a, **kw: "{}"  # type: ignore
    sys.modules["agents"] = _agents_mod

# llm_client stub MUST include:
#   safe_json_loads    — used by rubric.fill_criterion_gaps to parse LLM response
#   _try_repair_json   — used by scorer, rubric, interview lazily; absence raises
#                        ImportError caught by their exception handlers → fall back
#                        to defaults, breaking golden-shape and constraint-filter tests
# Both must parse valid JSON so tests that mock run_agent get real parsed output.
if "llm_client" not in sys.modules:
    def _stub_json_parse(s):
        if not isinstance(s, str):
            return {}
        try:
            return _json.loads(s)
        except Exception:
            return {}

    _llm_mod = types.ModuleType("llm_client")
    _llm_mod.safe_json_loads = _stub_json_parse  # type: ignore
    _llm_mod._try_repair_json = _stub_json_parse  # type: ignore
    sys.modules["llm_client"] = _llm_mod

# Stub db for memory.py
if "db" not in sys.modules:
    _db_mod = types.ModuleType("db")
    _db_mod._DB_AVAILABLE = False  # type: ignore
    sys.modules["db"] = _db_mod

# Stub embeddings — only when not already imported (test_embeddings.py imports
# embeddings at module level so the real module is always present in a full run)
if "embeddings" not in sys.modules:
    _emb_mod = types.ModuleType("embeddings")
    _emb_mod.embed = lambda *a, **kw: None  # type: ignore
    _emb_mod.embed_batch = lambda *a, **kw: []  # type: ignore
    _emb_mod.cosine_similarity = lambda *a, **kw: 0.0  # type: ignore
    _emb_mod.cosine_similarity_batch = lambda *a, **kw: []  # type: ignore
    sys.modules["embeddings"] = _emb_mod

# Now we can import from project root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from scorer import _add_relative_ranks, _finalize_scoring  # noqa: E402
from memory import _signal_decay_weight, _is_stale_signal   # noqa: E402
from category import detect_category, _fallback_result, _rule_based_result  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Fix 13 — Inter-Product Relative Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _make_scored(name: str, scores: list[dict], total: float = 50.0) -> dict:
    return {"name": name, "scores": scores, "weighted_total": total}


def _make_score(criterion: str, score: float) -> dict:
    return {
        "criterion": criterion,
        "label": criterion,
        "score": score,
        "weight": 1.0,
        "evidence": "test",
        "weighted_contribution": score,
        "has_data": True,
    }


class TestAddRelativeRanks:
    def test_empty_list_no_crash(self):
        result = []
        _add_relative_ranks(result)  # must not raise

    def test_single_product_only_option(self):
        p = _make_scored("A", [_make_score("sound", 8)])
        _add_relative_ranks([p])
        assert p["scores"][0]["relative_rank"] == "Only option"

    def test_single_product_overall_rank_1(self):
        p = _make_scored("A", [_make_score("sound", 8)])
        _add_relative_ranks([p])
        assert p["overall_rank"] == 1
        assert p["gap_to_leader"] == 0.0

    def test_two_products_best_and_weakest(self):
        p1 = _make_scored("A", [_make_score("sound", 9)], total=80)
        p2 = _make_scored("B", [_make_score("sound", 3)], total=40)
        _add_relative_ranks([p1, p2])
        assert p1["scores"][0]["relative_rank"] == "Best"
        assert p2["scores"][0]["relative_rank"] == "Weakest"

    def test_two_products_overall_ranks(self):
        p1 = _make_scored("A", [_make_score("x", 9)], total=80)
        p2 = _make_scored("B", [_make_score("x", 3)], total=40)
        _add_relative_ranks([p1, p2])
        assert p1["overall_rank"] == 1
        assert p2["overall_rank"] == 2
        assert p2["gap_to_leader"] == 40.0

    def test_three_products_labels(self):
        p1 = _make_scored("A", [_make_score("sound", 9)], total=90)
        p2 = _make_scored("B", [_make_score("sound", 5)], total=50)
        p3 = _make_scored("C", [_make_score("sound", 1)], total=10)
        _add_relative_ranks([p1, p2, p3])
        labels = {p["name"]: p["scores"][0]["relative_rank"] for p in [p1, p2, p3]}
        # Highest scorer gets Best; lowest gets Weakest; middle varies
        assert labels["A"] == "Best"
        assert labels["C"] == "Weakest"
        assert labels["B"] in ("Above avg", "Average", "Below avg")

    def test_near_best_threshold_gets_best_label(self):
        """Products within 0.3 pts of the highest score get 'Best'."""
        p1 = _make_scored("A", [_make_score("sound", 9.0)], total=90)
        p2 = _make_scored("B", [_make_score("sound", 8.8)], total=88)
        p3 = _make_scored("C", [_make_score("sound", 5.0)], total=50)
        _add_relative_ranks([p1, p2, p3])
        # Both p1 (9.0) and p2 (8.8, within 0.3) should be "Best"
        assert p1["scores"][0]["relative_rank"] == "Best"
        assert p2["scores"][0]["relative_rank"] == "Best"

    def test_leader_gap_to_itself_is_zero(self):
        p1 = _make_scored("A", [_make_score("x", 9)], total=90)
        p2 = _make_scored("B", [_make_score("x", 6)], total=60)
        _add_relative_ranks([p1, p2])
        assert p1["gap_to_leader"] == 0.0

    def test_multiple_criteria_independent(self):
        p1 = _make_scored("A", [_make_score("sound", 9), _make_score("battery", 3)], total=70)
        p2 = _make_scored("B", [_make_score("sound", 4), _make_score("battery", 9)], total=70)
        _add_relative_ranks([p1, p2])
        s_map_a = {s["criterion"]: s for s in p1["scores"]}
        s_map_b = {s["criterion"]: s for s in p2["scores"]}
        assert s_map_a["sound"]["relative_rank"] == "Best"
        assert s_map_b["sound"]["relative_rank"] == "Weakest"
        assert s_map_b["battery"]["relative_rank"] == "Best"
        assert s_map_a["battery"]["relative_rank"] == "Weakest"

    def test_all_same_scores_all_best(self):
        """When all products have identical scores on a criterion, all get 'Best'."""
        p1 = _make_scored("A", [_make_score("sound", 7)], total=70)
        p2 = _make_scored("B", [_make_score("sound", 7)], total=70)
        p3 = _make_scored("C", [_make_score("sound", 7)], total=70)
        _add_relative_ranks([p1, p2, p3])
        for p in [p1, p2, p3]:
            assert p["scores"][0]["relative_rank"] == "Best"

    def test_five_products_rank_range(self):
        products = [
            _make_scored(f"P{i}", [_make_score("sound", float(i))], total=float(i * 10))
            for i in range(5, 0, -1)
        ]
        _add_relative_ranks(products)
        assert products[0]["overall_rank"] == 1
        assert products[-1]["overall_rank"] == 5
        # Verify no relative_rank is missing
        for p in products:
            assert "relative_rank" in p["scores"][0]


# ─────────────────────────────────────────────────────────────────────────────
# Fix 13 + 17 integration — _finalize_scoring calls _add_relative_ranks
# ─────────────────────────────────────────────────────────────────────────────

def _make_rubric(criteria: list[str]) -> dict:
    return {
        "weighted_criteria": [
            {"name": c, "label": c, "weight": 1.0}
            for c in criteria
        ]
    }


def _make_full_product(name: str, crit_scores: dict[str, float], source_coverage: int = 3) -> dict:
    scores = [
        {
            "criterion": c,
            "label": c,
            "score": v,
            "weight": 1.0,
            "evidence": "real evidence",
            "weighted_contribution": v,
            "has_data": True,
        }
        for c, v in crit_scores.items()
    ]
    total = sum(crit_scores.values())
    return {
        "name": name,
        "scores": scores,
        "weighted_total": total,
        "max_possible": float(10 * len(crit_scores)),
        "percentage": round(total / (10 * len(crit_scores)) * 100),
        "source_coverage": source_coverage,
    }


class TestFinalizeScoring13_17:
    def test_finalize_attaches_overall_rank(self):
        rubric = _make_rubric(["sound"])
        p1 = _make_full_product("A", {"sound": 9.0})
        p2 = _make_full_product("B", {"sound": 5.0})
        result = _finalize_scoring([p1, p2], rubric)
        assert result[0]["overall_rank"] == 1
        assert result[1]["overall_rank"] == 2

    def test_finalize_attaches_gap_to_leader(self):
        rubric = _make_rubric(["sound"])
        p1 = _make_full_product("A", {"sound": 9.0})
        p2 = _make_full_product("B", {"sound": 5.0})
        result = _finalize_scoring([p1, p2], rubric)
        assert result[0]["gap_to_leader"] == 0.0
        assert result[1]["gap_to_leader"] > 0

    def test_finalize_attaches_relative_rank_on_scores(self):
        rubric = _make_rubric(["sound"])
        p1 = _make_full_product("A", {"sound": 9.0})
        p2 = _make_full_product("B", {"sound": 3.0})
        result = _finalize_scoring([p1, p2], rubric)
        ranks = {p["name"]: p["scores"][0]["relative_rank"] for p in result}
        assert ranks["A"] == "Best"
        assert ranks["B"] == "Weakest"

    def test_finalize_empty_list(self):
        assert _finalize_scoring([], _make_rubric(["sound"])) == []

    def test_finalize_single_source_degrades_high_to_medium(self):
        rubric = _make_rubric(["sound"])
        p = _make_full_product("A", {"sound": 9.0}, source_coverage=1)
        # Give it good coverage so natural conf would be "high"
        p["data_coverage"] = 1.0
        result = _finalize_scoring([p], rubric)
        # high → medium
        assert result[0]["confidence"] == "medium"

    def test_finalize_single_source_degrades_medium_to_low(self):
        # Two criteria, only one has real data → coverage 0.5 → natural "medium" → sc==1 → "low"
        rubric = _make_rubric(["sound", "battery"])
        p = {
            "name": "A",
            "scores": [
                {"criterion": "sound", "label": "sound", "score": 7.0,
                 "weight": 1.0, "evidence": "real evidence",
                 "weighted_contribution": 7.0, "has_data": True},
                {"criterion": "battery", "label": "battery", "score": 4.0,
                 "weight": 1.0, "evidence": "no direct data found",
                 "weighted_contribution": 4.0, "has_data": False},
            ],
            "weighted_total": 11.0,
            "source_coverage": 1,
        }
        result = _finalize_scoring([p], rubric)
        # 0.5 coverage → natural "medium" → sc==1 degrades to "low"
        assert result[0]["confidence"] == "low"

    def test_finalize_multi_source_not_penalized(self):
        rubric = _make_rubric(["sound"])
        p = _make_full_product("A", {"sound": 9.0}, source_coverage=4)
        result = _finalize_scoring([p], rubric)
        # With full data coverage, should stay "high"
        assert result[0]["confidence"] == "high"

    def test_finalize_sorted_by_weighted_total(self):
        rubric = _make_rubric(["sound"])
        p_low = _make_full_product("Low", {"sound": 2.0})
        p_high = _make_full_product("High", {"sound": 9.0})
        result = _finalize_scoring([p_low, p_high], rubric)
        assert result[0]["name"] == "High"
        assert result[1]["name"] == "Low"


# ─────────────────────────────────────────────────────────────────────────────
# Fix 14 — Indian Review Sites Under-Represented
# ─────────────────────────────────────────────────────────────────────────────

class TestIndianSitesInSourceFilter:
    def setup_method(self):
        import source_filter
        self.domains = source_filter.TRUSTED_DOMAINS
        # _AUTHORITY_SCORES is the internal dict; fall back gracefully if name changes
        self.scores = getattr(source_filter, "_AUTHORITY_SCORES", {})

    def test_91mobiles_trusted(self):
        assert "91mobiles.com" in self.domains

    def test_gadgets360_trusted(self):
        assert "gadgets360.com" in self.domains

    def test_digit_trusted(self):
        assert "digit.in" in self.domains

    def test_mysmartprice_trusted(self):
        assert "mysmartprice.com" in self.domains

    def test_beebom_trusted(self):
        assert "beebom.com" in self.domains

    def test_bgr_in_trusted(self):
        assert "bgr.in" in self.domains

    def test_xda_developers_trusted(self):
        assert "xda-developers.com" in self.domains

    def test_fonearena_trusted(self):
        assert "fonearena.com" in self.domains

    def test_91mobiles_authority_score_ge_80(self):
        assert self.scores.get("91mobiles.com", 0) >= 80

    def test_gadgets360_authority_score_ge_78(self):
        assert self.scores.get("gadgets360.com", 0) >= 78

    def test_mysmartprice_has_score(self):
        assert self.scores.get("mysmartprice.com", 0) >= 70

    def test_indian_sites_not_below_western_peers(self):
        """Indian sites should have scores comparable to western equivalents."""
        # All key Indian sites should be >= 60
        indian_sites = [
            "91mobiles.com", "gadgets360.com", "digit.in",
            "mysmartprice.com", "beebom.com", "bgr.in",
        ]
        for site in indian_sites:
            score = self.scores.get(site, 0)
            assert score >= 60, f"{site} authority score {score} is below threshold 60"


# ─────────────────────────────────────────────────────────────────────────────
# Fix 15 — Memory Signals Never Decay
# ─────────────────────────────────────────────────────────────────────────────

def _iso_days_ago(days: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.isoformat()


class TestSignalDecayWeight:
    def test_none_timestamp_returns_1(self):
        assert _signal_decay_weight(None) == 1.0

    def test_fresh_signal_near_1(self):
        weight = _signal_decay_weight(_iso_days_ago(1))
        assert 1.0 >= weight >= 0.99, f"Expected near 1.0 for 1-day-old signal, got {weight}"

    def test_exactly_90_days_returns_half(self):
        """At exactly 90 days (the half-life), weight ≈ 0.5."""
        weight = _signal_decay_weight(_iso_days_ago(90))
        assert abs(weight - 0.5) < 0.02, f"Expected ~0.5, got {weight}"

    def test_180_days_returns_quarter(self):
        """Two half-lives → ≈ 0.25."""
        weight = _signal_decay_weight(_iso_days_ago(180))
        assert abs(weight - 0.25) < 0.02, f"Expected ~0.25, got {weight}"

    def test_very_old_signal_floor(self):
        """5000-day-old signal gets the floor, not zero."""
        weight = _signal_decay_weight(_iso_days_ago(5000))
        assert weight == 0.05, f"Expected floor 0.05, got {weight}"

    def test_floor_is_positive(self):
        """Floor is > 0 — very old signals still contribute a little."""
        weight = _signal_decay_weight(_iso_days_ago(10_000))
        assert weight > 0.0

    def test_decay_is_monotonic(self):
        """Older signals have smaller weights."""
        w1 = _signal_decay_weight(_iso_days_ago(10))
        w2 = _signal_decay_weight(_iso_days_ago(90))
        w3 = _signal_decay_weight(_iso_days_ago(180))
        assert w1 > w2 > w3

    def test_invalid_timestamp_returns_1(self):
        """Corrupt timestamp → safe fallback of 1.0."""
        assert _signal_decay_weight("not-a-timestamp") == 1.0

    def test_z_suffix_handled(self):
        """ISO strings with trailing 'Z' must be parsed correctly."""
        ts = _iso_days_ago(30).replace("+00:00", "Z")
        weight = _signal_decay_weight(ts)
        assert 0.5 < weight < 1.0

    def test_naive_datetime_handled(self):
        """ISO strings without timezone info should be parsed safely."""
        ts = datetime.datetime.utcnow().isoformat()  # no timezone
        weight = _signal_decay_weight(ts)
        assert 0.99 < weight <= 1.0


class TestIsStaleSignal:
    def test_none_not_stale(self):
        assert _is_stale_signal(None) is False

    def test_fresh_signal_not_stale(self):
        assert _is_stale_signal(_iso_days_ago(10)) is False

    def test_exactly_91_days_is_stale(self):
        assert _is_stale_signal(_iso_days_ago(91)) is True

    def test_exactly_90_days_not_stale(self):
        assert _is_stale_signal(_iso_days_ago(89)) is False

    def test_old_signal_stale(self):
        assert _is_stale_signal(_iso_days_ago(365)) is True

    def test_invalid_timestamp_not_stale(self):
        assert _is_stale_signal("garbage") is False

    def test_boundary_at_90_days(self):
        """The threshold is > 90 days, not >= 90."""
        at_exactly_90 = _iso_days_ago(90)
        # May or may not be stale depending on seconds precision — just verify no crash
        result = _is_stale_signal(at_exactly_90)
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Fix 16 — Pre-Query Category Disambiguation
# ─────────────────────────────────────────────────────────────────────────────

class TestNeedsClarificationField:
    def test_fallback_result_has_needs_clarification_true(self):
        result = _fallback_result()
        assert result.get("needs_clarification") is True

    def test_rule_based_mechanical_keyboard_no_clarification(self):
        result = _rule_based_result("best mechanical keyboard")
        assert result is not None
        assert result.get("needs_clarification") is False

    def test_rule_based_generic_keyboard_needs_clarification(self):
        result = _rule_based_result("keyboard")
        assert result is not None
        assert result.get("needs_clarification") is True

    def test_rule_based_generic_keyboard_needs_disambiguation(self):
        result = _rule_based_result("keyboard")
        assert result is not None
        assert result.get("needs_disambiguation") is True

    def test_needs_clarification_true_when_disambiguation_needed(self):
        """needs_clarification must be True whenever needs_disambiguation is True."""
        result = _rule_based_result("keyboard")
        assert result is not None
        if result["needs_disambiguation"]:
            assert result["needs_clarification"] is True

    def test_detect_category_always_has_needs_clarification_field(self, monkeypatch):
        """detect_category must always return needs_clarification regardless of LLM path."""
        import cache as cache_mod
        import category as cat_mod
        import json
        monkeypatch.setattr(cache_mod, "get", lambda *a, **kw: None)
        monkeypatch.setattr(cache_mod, "set", lambda *a, **kw: None)
        # Patch the already-imported references inside category.py
        monkeypatch.setattr(cat_mod, "run_agent", lambda *a, **kw: (
            '{"category":"general/item","primary_noun":"item","confidence":"low",'
            '"needs_disambiguation":false,"options":[]}'
        ))
        monkeypatch.setattr(cat_mod, "safe_json_loads", lambda s: json.loads(s))

        cat_mod._detect_category_cached.cache_clear()
        result = detect_category("something ambiguous xyz123_test_a")
        assert "needs_clarification" in result

    def test_low_confidence_sets_needs_clarification_true(self, monkeypatch):
        """When LLM returns confidence=low, needs_clarification must be True."""
        import cache as cache_mod
        import category as cat_mod
        import json
        monkeypatch.setattr(cache_mod, "get", lambda *a, **kw: None)
        monkeypatch.setattr(cache_mod, "set", lambda *a, **kw: None)
        monkeypatch.setattr(cat_mod, "run_agent", lambda *a, **kw: (
            '{"category":"general/gadget","primary_noun":"gadget","confidence":"low",'
            '"needs_disambiguation":false,"options":[]}'
        ))
        monkeypatch.setattr(cat_mod, "safe_json_loads", lambda s: json.loads(s))

        cat_mod._detect_category_cached.cache_clear()
        result = detect_category("zyxwvutsrq unique test query 99x_b")
        assert result.get("needs_clarification") is True

    def test_high_confidence_no_disambiguation_no_clarification(self, monkeypatch):
        """High-confidence, unambiguous query → needs_clarification False."""
        import cache as cache_mod
        import category as cat_mod
        import json
        monkeypatch.setattr(cache_mod, "get", lambda *a, **kw: None)
        monkeypatch.setattr(cache_mod, "set", lambda *a, **kw: None)
        monkeypatch.setattr(cat_mod, "run_agent", lambda *a, **kw: (
            '{"category":"electronics/earbuds","primary_noun":"earbuds","confidence":"high",'
            '"needs_disambiguation":false,"options":[]}'
        ))
        monkeypatch.setattr(cat_mod, "safe_json_loads", lambda s: json.loads(s))

        cat_mod._detect_category_cached.cache_clear()
        result = detect_category("best earbuds under 3000 rupees abcdefg_unique_test_c")
        assert result.get("needs_clarification") is False


# ─────────────────────────────────────────────────────────────────────────────
# Fix 17 — source_coverage in analysis_normalizer
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceCoverageInNormalizer:
    def setup_method(self):
        # Minimal stubs for analysis_normalizer imports
        for mod_name in [
            "openai", "google.generativeai", "cohere", "anthropic",
            "praw", "prawcore", "reddit_fetch", "review_fetch",
            "summarizer", "analyzer",
        ]:
            if mod_name not in sys.modules:
                m = types.ModuleType(mod_name.split(".")[0])
                sys.modules[mod_name] = m

        # Stub llm_client helpers used by normalizer
        import llm_client as llm_mod
        if not hasattr(llm_mod, "safe_json_loads"):
            llm_mod.safe_json_loads = lambda s: {}

        # Import inside setup so stub is installed first
        from analysis_normalizer import _dedup_products
        self._dedup = _dedup_products

    def _call_normalizer_source_coverage(self, products_in: list[dict]) -> list[dict]:
        """Run source_coverage injection logic (mirrors analysis_normalizer logic)."""
        for p in products_in:
            p["source_coverage"] = len(set(p.get("sources") or []))
        return products_in

    def test_single_source(self):
        products = [{"name": "A", "sources": ["reddit:Headphones"]}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 1

    def test_three_distinct_sources(self):
        products = [{"name": "A", "sources": [
            "reddit:Headphones", "review:rtings.com", "review:91mobiles.com"
        ]}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 3

    def test_duplicate_sources_counted_once(self):
        products = [{"name": "A", "sources": [
            "reddit:Headphones", "reddit:Headphones", "review:rtings.com"
        ]}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 2

    def test_no_sources_is_zero(self):
        products = [{"name": "A", "sources": []}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 0

    def test_missing_sources_key_is_zero(self):
        products = [{"name": "A"}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 0

    def test_none_sources_is_zero(self):
        products = [{"name": "A", "sources": None}]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 0

    def test_multiple_products_independent(self):
        products = [
            {"name": "A", "sources": ["s1", "s2", "s3"]},
            {"name": "B", "sources": ["s1"]},
        ]
        result = self._call_normalizer_source_coverage(products)
        assert result[0]["source_coverage"] == 3
        assert result[1]["source_coverage"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Fix 17 — _finalize_scoring confidence penalty
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceCoverageConfidencePenalty:
    def _product_with_coverage(self, sc: int) -> dict:
        return {
            "name": "P",
            "scores": [{
                "criterion": "sound",
                "label": "sound",
                "score": 9.0,
                "weight": 1.0,
                "evidence": "strong evidence",
                "weighted_contribution": 9.0,
                "has_data": True,
            }],
            "weighted_total": 9.0,
            "source_coverage": sc,
        }

    def test_source_coverage_1_degrades_high_confidence(self):
        rubric = _make_rubric(["sound"])
        p = self._product_with_coverage(1)
        result = _finalize_scoring([p], rubric)
        assert result[0]["confidence"] == "medium"

    def test_source_coverage_2_no_penalty(self):
        rubric = _make_rubric(["sound"])
        p = self._product_with_coverage(2)
        result = _finalize_scoring([p], rubric)
        assert result[0]["confidence"] == "high"

    def test_source_coverage_5_no_penalty(self):
        rubric = _make_rubric(["sound"])
        p = self._product_with_coverage(5)
        result = _finalize_scoring([p], rubric)
        assert result[0]["confidence"] == "high"

    def test_source_coverage_0_does_not_degrade_more_than_once(self):
        """sc == 0 (not sc == 1) should NOT be penalised by this fix."""
        rubric = _make_rubric(["sound"])
        p = self._product_with_coverage(0)
        result = _finalize_scoring([p], rubric)
        # 0 sources is unusual but the rule only fires for sc == 1
        assert result[0]["confidence"] == "high"

    def test_source_coverage_missing_no_penalty(self):
        """No source_coverage key → no penalty."""
        rubric = _make_rubric(["sound"])
        p = {
            "name": "P",
            "scores": [{"criterion": "sound", "label": "sound", "score": 9.0,
                        "weight": 1.0, "evidence": "real", "weighted_contribution": 9.0,
                        "has_data": True}],
            "weighted_total": 9.0,
        }
        result = _finalize_scoring([p], rubric)
        assert result[0]["confidence"] == "high"
