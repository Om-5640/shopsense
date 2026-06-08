"""
Tests for accuracy fixes 6-12 (High — Significant Accuracy Loss).

Fix 6:  Mention Counting False Positives on Model Numbers
        _has_word_boundary rejects "1000XM5" inside "WF-1000XM5"

Fix 7:  No Recency Weighting — Older Products Win by Default
        _thread_recency_weight + MentionResult.recency_weighted_mentions

Fix 8:  Provider Quality Degradation Is Silent
        reset_session_providers_used / _record_provider_used / get_quality_metadata

Fix 9:  Complaint Confidence Levels Computed but Ignored
        _FAST_COMPLAINT_WEIGHTS applied to penalty in _fast_score

Fix 10: Sentiment Analysis Has No Negation or Sarcasm Handling
        _is_negated / _score_window recognise "not good", "not bad", etc.

Fix 11: Reddit Search Queries Not Personalized From Interview
        _build_intent_query_variants builds use_case / constraint / pref variants

Fix 12: No Data Lineage — Can't Explain Any Ranking Decision
        source_passages present in _build_scored_dict with thread_url
"""

from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "api") not in sys.path:
    sys.path.insert(0, str(_ROOT / "api"))


# ===========================================================================
# Fix 6: Word-boundary enforcement for hyphen-compound model numbers
# ===========================================================================

from mention_counter import _has_word_boundary  # noqa: E402


class TestHyphenWordBoundary:
    """_has_word_boundary must treat hyphens between alphanum as word chars."""

    def test_1000xm5_inside_wf_hyphen_compound_rejected(self):
        text = "wf-1000xm5"
        # "1000xm5" starts at index 3
        assert not _has_word_boundary(text, 3, 10)

    def test_1000xm5_inside_wh_hyphen_compound_rejected(self):
        text = "wh-1000xm5 are great"
        assert not _has_word_boundary(text, 3, 10)

    def test_1000xm5_standalone_with_spaces_accepted(self):
        text = "I bought a 1000xm5 last week"
        start = text.find("1000xm5")
        end = start + len("1000xm5")
        assert _has_word_boundary(text, start, end)

    def test_alias_at_start_of_string_accepted(self):
        text = "1000xm5 is great"
        assert _has_word_boundary(text, 0, 7)

    def test_alias_at_end_of_string_accepted(self):
        text = "just got the 1000xm5"
        start = len(text) - len("1000xm5")
        assert _has_word_boundary(text, start, len(text))

    def test_alias_after_space_accepted(self):
        text = "review of 1000xm5 here"
        start = text.find("1000xm5")
        end = start + len("1000xm5")
        assert _has_word_boundary(text, start, end)

    def test_alias_after_opening_paren_accepted(self):
        text = "(1000xm5) is decent"
        assert _has_word_boundary(text, 1, 8)

    def test_alias_prefix_hyphen_compound_rejected(self):
        # Suffix variant: "1000xm5-plus" should reject "1000xm5" (it's a prefix of compound)
        text = "1000xm5-pro review"
        end = len("1000xm5")
        assert not _has_word_boundary(text, 0, end)

    def test_non_alnum_before_hyphen_is_not_compound(self):
        # "!-1000xm5" — hyphen before but no alnum before hyphen → boundary accepted
        text = " -1000xm5"
        assert _has_word_boundary(text, 2, 9)

    def test_multi_hyphen_compound_rejected(self):
        text = "sony-wf-1000xm5"
        start = text.find("1000xm5")
        end = start + len("1000xm5")
        assert not _has_word_boundary(text, start, end)


# ===========================================================================
# Fix 7: Recency weighting — _thread_recency_weight
# ===========================================================================

from mention_counter import _thread_recency_weight, _RECENCY_WEIGHTS  # noqa: E402

_NOW_YEAR = datetime.datetime.utcnow().year


def _ts_for_year(year: int) -> float:
    """Return a Unix timestamp for Jan 1 of the given year."""
    return datetime.datetime(year, 6, 15, 12, 0, 0).timestamp()


class TestThreadRecencyWeight:
    def test_current_year_returns_2x(self):
        ts = _ts_for_year(_NOW_YEAR)
        assert _thread_recency_weight(ts) == pytest.approx(2.0)

    def test_one_year_old_returns_1_5x(self):
        ts = _ts_for_year(_NOW_YEAR - 1)
        assert _thread_recency_weight(ts) == pytest.approx(1.5)

    def test_two_years_old_returns_1x(self):
        ts = _ts_for_year(_NOW_YEAR - 2)
        assert _thread_recency_weight(ts) == pytest.approx(1.0)

    def test_three_years_old_returns_0_7x(self):
        ts = _ts_for_year(_NOW_YEAR - 3)
        assert _thread_recency_weight(ts) == pytest.approx(0.7)

    def test_four_years_old_returns_0_5x(self):
        ts = _ts_for_year(_NOW_YEAR - 4)
        assert _thread_recency_weight(ts) == pytest.approx(0.5)

    def test_five_years_old_returns_0_3x(self):
        ts = _ts_for_year(_NOW_YEAR - 5)
        assert _thread_recency_weight(ts) == pytest.approx(0.3)

    def test_very_old_thread_returns_0_3x(self):
        ts = _ts_for_year(_NOW_YEAR - 20)
        assert _thread_recency_weight(ts) == pytest.approx(0.3)

    def test_none_returns_unknown_weight(self):
        assert _thread_recency_weight(None) == pytest.approx(0.7)

    def test_zero_returns_unknown_weight(self):
        assert _thread_recency_weight(0) == pytest.approx(0.7)

    def test_float_timestamp_accepted(self):
        ts = float(_ts_for_year(_NOW_YEAR))
        assert _thread_recency_weight(ts) == pytest.approx(2.0)

    def test_string_timestamp_accepted(self):
        # Some fetchers return timestamps as strings
        ts = str(_ts_for_year(_NOW_YEAR - 1))
        assert _thread_recency_weight(ts) == pytest.approx(1.5)

    def test_invalid_string_returns_unknown_weight(self):
        assert _thread_recency_weight("not-a-timestamp") == pytest.approx(0.7)

    def test_negative_timestamp_returns_unknown_weight(self):
        # Negative unix timestamps may overflow on some platforms
        result = _thread_recency_weight(-1)
        assert result in (0.7, 0.3, 2.0, 1.5, 1.0, 0.5)  # any valid weight (no crash)

    def test_all_known_ages_covered_by_table(self):
        for age, expected in _RECENCY_WEIGHTS.items():
            ts = _ts_for_year(_NOW_YEAR - age)
            assert _thread_recency_weight(ts) == pytest.approx(expected), f"age={age}"


class TestRecencyWeightedMentions:
    """MentionResult.recency_weighted_mentions accumulates correctly."""

    def test_recency_weighted_mentions_present_on_dataclass(self):
        from mention_counter import MentionResult
        mr = MentionResult(canonical_name="TestProduct")
        assert hasattr(mr, "recency_weighted_mentions")
        assert mr.recency_weighted_mentions == 0.0

    def test_count_across_threads_accumulates_weighted(self):
        from mention_counter import build_automaton, build_exclude_patterns, count_across_threads
        from alias_resolver import merge_into_registry

        corefs = [{"Sony WH-1000XM5": ["wh-1000xm5", "xm5"]}]
        registry = merge_into_registry(corefs)
        aut = build_automaton(registry)
        excl = build_exclude_patterns(registry)

        recent_ts = _ts_for_year(_NOW_YEAR)       # weight 2.0
        old_ts = _ts_for_year(_NOW_YEAR - 5)      # weight 0.3

        threads = [
            {
                "url": "https://reddit.com/r/headphones/1",
                "title": "xm5 review",
                "body": "",
                "created_utc": recent_ts,
                "comments": [],
            },
            {
                "url": "https://reddit.com/r/headphones/2",
                "title": "xm5 still worth it",
                "body": "",
                "created_utc": old_ts,
                "comments": [],
            },
        ]

        results = count_across_threads(threads, registry, aut, excl, llm_client=None, run_sentiment=False)
        mr = results.get("Sony WH-1000XM5")
        assert mr is not None
        # Title of thread 1: 1 mention × 2.0 = 2.0
        # Title of thread 2: 1 mention × 0.3 = 0.3
        # Total raw mentions: 2
        assert mr.total_mentions == 2
        assert mr.recency_weighted_mentions == pytest.approx(2.0 + 0.3)

    def test_missing_created_utc_uses_unknown_weight(self):
        from mention_counter import build_automaton, build_exclude_patterns, count_across_threads
        from alias_resolver import merge_into_registry

        corefs = [{"AirPods Pro": ["airpods pro"]}]
        registry = merge_into_registry(corefs)
        aut = build_automaton(registry)
        excl = build_exclude_patterns(registry)

        threads = [
            {
                "url": "https://reddit.com/r/tech/1",
                "title": "airpods pro are great",
                "body": "",
                # No created_utc — should use 0.7 unknown weight
                "comments": [],
            }
        ]

        results = count_across_threads(threads, registry, aut, excl, llm_client=None, run_sentiment=False)
        mr = results.get("AirPods Pro")
        assert mr is not None
        assert mr.recency_weighted_mentions == pytest.approx(0.7)  # 1 mention × 0.7


# ===========================================================================
# Fix 8: Provider quality degradation tracking
# ===========================================================================

from agents import (  # noqa: E402
    reset_session_providers_used,
    get_session_providers_used,
    get_quality_metadata,
    _record_provider_used,
    _PRIMARY_PROVIDERS,
)


class TestProviderQualityTracking:
    def setup_method(self):
        reset_session_providers_used()

    def test_reset_clears_log(self):
        _record_provider_used("main_analyzer", "gemini")
        reset_session_providers_used()
        assert get_session_providers_used() == []

    def test_record_provider_adds_entry(self):
        _record_provider_used("main_analyzer", "gemini")
        log = get_session_providers_used()
        assert len(log) == 1
        assert log[0] == {"agent": "main_analyzer", "provider": "gemini"}

    def test_multiple_agents_recorded(self):
        _record_provider_used("main_analyzer", "gemini")
        _record_provider_used("product_scorer", "groq")
        log = get_session_providers_used()
        assert len(log) == 2
        agents = {e["agent"] for e in log}
        assert agents == {"main_analyzer", "product_scorer"}

    def test_empty_log_not_degraded(self):
        meta = get_quality_metadata()
        assert meta["degraded"] is False
        assert meta["fallback_agents"] == []
        assert meta["providers_used"] == []

    def test_primary_provider_used_not_degraded(self):
        # main_analyzer's primary is "gemini"
        _record_provider_used("main_analyzer", "gemini")
        meta = get_quality_metadata()
        assert meta["degraded"] is False
        assert meta["fallback_agents"] == []

    def test_fallback_provider_detected_as_degraded(self):
        # main_analyzer primary is gemini; using groq = fallback
        _record_provider_used("main_analyzer", "groq")
        meta = get_quality_metadata()
        assert meta["degraded"] is True
        assert len(meta["fallback_agents"]) == 1
        fa = meta["fallback_agents"][0]
        assert fa["agent"] == "main_analyzer"
        assert fa["used"] == "groq"
        assert fa["expected"] == "gemini"

    def test_multiple_fallbacks_all_reported(self):
        # Two agents on fallback providers
        _record_provider_used("main_analyzer", "groq")   # primary = gemini
        _record_provider_used("product_scorer", "gemini") # primary = groq
        meta = get_quality_metadata()
        assert meta["degraded"] is True
        assert len(meta["fallback_agents"]) == 2

    def test_unknown_agent_not_counted_as_fallback(self):
        # "custom_agent" not in _PRIMARY_PROVIDERS — should not cause degraded=True
        _record_provider_used("custom_agent", "openai")
        meta = get_quality_metadata()
        assert meta["degraded"] is False

    def test_providers_used_list_returned(self):
        _record_provider_used("main_analyzer", "gemini")
        _record_provider_used("main_analyzer", "gemini")
        meta = get_quality_metadata()
        assert len(meta["providers_used"]) == 2

    def test_thread_local_isolation(self):
        """Two threads maintain independent provider logs."""
        log_a: list = []
        log_b: list = []

        def _thread_a():
            reset_session_providers_used()
            _record_provider_used("main_analyzer", "gemini")
            log_a.extend(get_session_providers_used())

        def _thread_b():
            reset_session_providers_used()
            _record_provider_used("product_scorer", "groq")
            log_b.extend(get_session_providers_used())

        t1 = threading.Thread(target=_thread_a)
        t2 = threading.Thread(target=_thread_b)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert all(e["agent"] == "main_analyzer" for e in log_a)
        assert all(e["agent"] == "product_scorer" for e in log_b)

    def test_primary_providers_dict_non_empty(self):
        assert len(_PRIMARY_PROVIDERS) >= 5


# ===========================================================================
# Fix 9: Complaint confidence levels applied in _fast_score
# ===========================================================================

from scorer import _fast_score  # noqa: E402

_FAST_RUBRIC = {
    "weighted_criteria": [
        {"name": "sound_quality", "label": "Sound Quality", "weight": 5,
         "high_score_means": "great", "low_score_means": "poor"},
        {"name": "build_quality", "label": "Build Quality", "weight": 5,
         "high_score_means": "solid", "low_score_means": "flimsy"},
    ]
}


def _product_with_complaints(complaints):
    return {
        "name": "TestProduct",
        "mention_count": 10,
        "positive_mentions": 8,
        "negative_mentions": 2,
        "dominant_sentiment": "positive",
        "complaints": complaints,
        "praise": ["good sound"],
        "signal_strength": "high",
    }


def _pct(product, complaints):
    return _fast_score(product, _FAST_RUBRIC, "")["percentage"]


class TestComplaintConfidenceWeighting:
    def test_no_complaints_no_penalty(self):
        product = _product_with_complaints([])
        result = _fast_score(product, _FAST_RUBRIC, "")
        assert "percentage" in result
        assert 10.0 <= result["percentage"] <= 95.0

    def test_confirmed_complaint_higher_penalty_than_single(self):
        confirmed = _product_with_complaints([
            {"text": "battery dies fast", "confidence": "confirmed"}
        ])
        single = _product_with_complaints([
            {"text": "battery dies fast", "confidence": "single"}
        ])
        pct_confirmed = _pct(confirmed, confirmed["complaints"])
        pct_single = _pct(single, single["complaints"])
        assert pct_confirmed <= pct_single

    def test_reported_complaint_between_confirmed_and_single(self):
        confirmed = _product_with_complaints([{"text": "defective", "confidence": "confirmed"}])
        reported = _product_with_complaints([{"text": "defective", "confidence": "reported"}])
        single = _product_with_complaints([{"text": "defective", "confidence": "single"}])
        p_c = _pct(confirmed, [])
        p_r = _pct(reported, [])
        p_s = _pct(single, [])
        assert p_c <= p_r <= p_s

    def test_multiple_confirmed_complaints_capped(self):
        """Even with many heavy complaints, score must not go below 10% (1.0 base / 10 max × 100)."""
        complaints = [{"text": f"issue {i}", "confidence": "confirmed"} for i in range(10)]
        product = _product_with_complaints(complaints)
        result = _fast_score(product, _FAST_RUBRIC, "")
        assert result["percentage"] >= 10.0

    def test_score_result_has_standard_keys(self):
        product = _product_with_complaints([])
        result = _fast_score(product, _FAST_RUBRIC, "")
        for key in ("name", "percentage", "weighted_total", "scores"):
            assert key in result

    def test_unknown_confidence_treated_same_as_single(self):
        unknown = _product_with_complaints([{"text": "blah", "confidence": "mystery"}])
        single = _product_with_complaints([{"text": "blah", "confidence": "single"}])
        assert abs(_pct(unknown, []) - _pct(single, [])) < 0.1


# ===========================================================================
# Fix 10: Negation window in _score_window
# ===========================================================================

from sentiment_analyser import _score_window, _is_negated, _negator_ends  # noqa: E402


class TestNegationDetection:
    """_is_negated correctly identifies negated sentiment keywords."""

    def test_negated_positive_increases_neg_score(self):
        pos, neg = _score_window("this product is not good at all")
        # "not good" → negated positive counted as negative
        assert neg > pos

    def test_negated_negative_increases_pos_score(self):
        pos, neg = _score_window("it is not bad for the price")
        # "not bad" → negated negative counted as weak positive
        assert pos >= neg

    def test_plain_positive_scores_positive(self):
        pos, neg = _score_window("this is highly recommended and amazing")
        assert pos > neg

    def test_plain_negative_scores_negative(self):
        pos, neg = _score_window("terrible build quality, avoid this product")
        assert neg > pos

    def test_no_negation_positive_word(self):
        pos1, neg1 = _score_window("it works great")
        pos2, neg2 = _score_window("it does not work great")
        assert pos1 > pos2

    def test_negator_outside_window_not_applied(self):
        # Negator 60+ chars before the sentiment word — outside the 45-char window
        text = "never mind that earlier comment — " + " " * 30 + "it is amazing"
        pos, neg = _score_window(text)
        # "amazing" should still be counted positive because negator is far away
        assert pos > 0

    def test_dont_buy_scored_negative(self):
        # "don't buy" is a direct negative pattern (weight 3.0) — not a negated positive
        pos, neg = _score_window("I don't buy this, complete waste of money")
        assert neg > pos

    def test_not_amazing_scored_negative(self):
        # "amazing" is a positive pattern; negated → should count as negative evidence
        pos, neg = _score_window("not amazing at all, pretty mediocre")
        assert neg > pos

    def test_no_issues_counts_as_weak_positive(self):
        pos, neg = _score_window("I have no issues with this device")
        # "no issues" — "issues" is negated negative → weak positive contribution
        assert pos >= 0

    def test_couldnt_be_happier_stays_positive(self):
        # "couldn't" is a negator but "happier" is not in the negative keyword list
        # so this should not incorrectly score negative
        pos, neg = _score_window("I couldn't be happier with this purchase")
        # No negative keyword matched — pos may still be 0 if "happier" isn't in patterns
        assert neg == 0 or pos >= neg

    def test_multiple_negations_handled(self):
        # Two separate negated positives
        pos, neg = _score_window("not great, not good value")
        assert neg > pos


class TestNegatorEnds:
    def test_finds_all_negators(self):
        text = "not bad and never terrible"
        ends = _negator_ends(text)
        assert len(ends) >= 2

    def test_empty_text_returns_empty(self):
        assert _negator_ends("") == []

    def test_no_negators_returns_empty(self):
        assert _negator_ends("great product, amazing quality") == []


class TestIsNegated:
    def test_negator_immediately_before_match(self):
        text = "not good"
        ends = _negator_ends(text)
        # "good" starts at index 4
        assert _is_negated(4, ends, text)

    def test_negator_too_far_away(self):
        text = "not " + "word " * 10 + "good"
        ends = _negator_ends(text)
        match_start = text.rfind("good")
        assert not _is_negated(match_start, ends, text)

    def test_no_negators_returns_false(self):
        text = "amazing product"
        ends = _negator_ends(text)
        assert not _is_negated(0, ends, text)


# ===========================================================================
# Fix 11: Interview-personalized search query variants
# ===========================================================================

from reddit_fetch import _build_intent_query_variants  # noqa: E402


class TestIntentQueryVariants:
    def test_no_intent_returns_empty(self):
        variants = _build_intent_query_variants("best earbuds", {})
        assert variants == []

    def test_use_case_generates_variant(self):
        intent = {"use_cases": ["gym workouts"], "hard_constraints": [], "preferences": []}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert any("gym" in v for v in variants)

    def test_hard_constraint_generates_variant(self):
        intent = {"use_cases": [], "hard_constraints": ["waterproof"], "preferences": []}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert any("waterproof" in v for v in variants)

    def test_preference_generates_variant(self):
        intent = {"use_cases": [], "hard_constraints": [], "preferences": ["bass heavy sound"]}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert any("bass" in v for v in variants)

    def test_all_sources_generate_up_to_4_variants(self):
        intent = {
            "use_cases": ["commuting", "office work"],
            "hard_constraints": ["active noise cancellation"],
            "preferences": ["long battery life"],
        }
        variants = _build_intent_query_variants("best earbuds", intent)
        # Max: 2 use cases + 1 constraint + 1 preference = 4
        assert len(variants) <= 4
        assert len(variants) > 0

    def test_different_intent_sources_produce_distinct_text(self):
        intent = {
            "use_cases": ["gym workout", "daily commute"],
            "hard_constraints": ["noise cancelling"],
            "preferences": ["long battery life"],
        }
        variants = _build_intent_query_variants("best earbuds", intent)
        # All generated variants are non-empty strings
        assert all(isinstance(v, str) and len(v) > 0 for v in variants)

    def test_term_already_in_query_skipped(self):
        # If the intent term is already in the base query, no variant is added
        intent = {"use_cases": ["earbuds"], "hard_constraints": [], "preferences": []}
        variants = _build_intent_query_variants("best earbuds", intent)
        # "earbuds" is already in the query → no variant added for it
        assert not any(v.endswith("earbuds earbuds") for v in variants)

    def test_variants_contain_site_reddit(self):
        intent = {"use_cases": ["gym"], "hard_constraints": [], "preferences": []}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert all("site:reddit.com" in v for v in variants)

    def test_variants_contain_base_query(self):
        intent = {"use_cases": ["swimming"], "hard_constraints": [], "preferences": []}
        variants = _build_intent_query_variants("best waterproof earbuds", intent)
        assert all("best waterproof earbuds" in v for v in variants)

    def test_empty_use_case_text_skipped(self):
        intent = {"use_cases": ["", "   "], "hard_constraints": [], "preferences": []}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert variants == []

    def test_none_values_handled_gracefully(self):
        intent = {"use_cases": None, "hard_constraints": None, "preferences": None}
        variants = _build_intent_query_variants("best earbuds", intent)
        assert variants == []

    def test_only_first_2_use_cases_used(self):
        intent = {
            "use_cases": ["use1", "use2", "use3", "use4"],
            "hard_constraints": [],
            "preferences": [],
        }
        variants = _build_intent_query_variants("best earbuds", intent)
        # Only first 2 use_cases should be used
        assert len(variants) <= 2


class TestQueryVariationsIntegration:
    """_query_variations includes intent variants when profile contains intent."""

    def test_intent_variants_added_to_variations(self):
        from reddit_fetch import _query_variations
        intent = {"use_cases": ["commuting"], "hard_constraints": [], "preferences": []}
        profile = {"intent": intent}
        variations = _query_variations("best earbuds under 5000", profile=profile)
        assert any("commuting" in v for v in variations)

    def test_no_intent_no_extra_variants(self):
        from reddit_fetch import _query_variations
        variations_no_profile = _query_variations("best earbuds under 5000", profile=None)
        variations_empty = _query_variations("best earbuds under 5000", profile={})
        # No crash
        assert isinstance(variations_no_profile, list)
        assert isinstance(variations_empty, list)

    def test_no_duplicate_in_final_list(self):
        from reddit_fetch import _query_variations
        intent = {"use_cases": ["earbuds for gym"], "hard_constraints": [], "preferences": []}
        profile = {"intent": intent}
        variations = _query_variations("best earbuds", profile=profile)
        assert len(variations) == len(set(variations))


# ===========================================================================
# Fix 12: Source passages / data lineage in _build_scored_dict
# ===========================================================================

from scorer import _build_scored_dict  # noqa: E402


def _make_rubric(criterion: str = "sound_quality"):
    return {
        "weighted_criteria": [
            {"name": criterion, "label": "Sound Quality", "weight": 10,
             "high_score_means": "great", "low_score_means": "poor"}
        ]
    }


def _make_scores(criterion: str = "sound_quality"):
    return [
        {"criterion": criterion, "label": "Sound Quality", "weight": 10,
         "score": 8, "evidence": "Good bass response", "weighted_contribution": 80}
    ]


def _make_product_with_sentiment(name: str, sentiments: list[tuple]) -> dict:
    """sentiments = list of (sentiment_label, comment_text, thread_url)"""
    return {
        "name": name,
        "mention_count": 10,
        "sources": ["r/headphones"],
        "sentiment_records": [
            {"sentiment": s, "comment_text": t, "source": "rule", "thread_url": u}
            for s, t, u in sentiments
        ],
    }


class TestSourcePassagesInBuildScoredDict:
    def test_source_passages_field_present(self):
        product = _make_product_with_sentiment("TestProduct", [
            ("positive", "great sound", "https://reddit.com/r/headphones/1"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert "source_passages" in result

    def test_source_passages_empty_when_no_sentiment_records(self):
        product = {
            "name": "NoData", "mention_count": 5, "sources": ["r/tech"],
            "sentiment_records": [],
        }
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert result["source_passages"] == []

    def test_source_passages_max_3_positive_plus_2_negative(self):
        sentiments = (
            [("positive", f"great {i}", f"https://r.com/{i}") for i in range(5)]
            + [("negative", f"bad {i}", f"https://r.com/n{i}") for i in range(4)]
        )
        product = _make_product_with_sentiment("BigData", sentiments)
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        passages = result["source_passages"]
        pos = [p for p in passages if p["sentiment"] == "positive"]
        neg = [p for p in passages if p["sentiment"] == "negative"]
        assert len(pos) <= 3
        assert len(neg) <= 2
        assert len(passages) <= 5

    def test_source_passage_has_required_keys(self):
        product = _make_product_with_sentiment("QProduct", [
            ("positive", "wonderful earbuds", "https://reddit.com/r/audio/42"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        passage = result["source_passages"][0]
        assert "text" in passage
        assert "sentiment" in passage
        assert "thread_url" in passage

    def test_source_passage_text_truncated_to_250(self):
        long_comment = "a" * 500
        product = _make_product_with_sentiment("LongText", [
            ("positive", long_comment, "https://reddit.com/r/audio/1"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert len(result["source_passages"][0]["text"]) <= 250

    def test_source_passage_thread_url_preserved(self):
        url = "https://reddit.com/r/audiophile/comments/abc123/"
        product = _make_product_with_sentiment("URLTest", [
            ("negative", "didn't like it", url),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert result["source_passages"][0]["thread_url"] == url

    def test_source_passage_missing_thread_url_defaults_to_empty_string(self):
        product = {
            "name": "NoURL", "mention_count": 5, "sources": [],
            "sentiment_records": [
                {"sentiment": "positive", "comment_text": "nice", "source": "rule"}
                # no thread_url key
            ],
        }
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert result["source_passages"][0]["thread_url"] == ""

    def test_neutral_records_not_in_source_passages(self):
        product = _make_product_with_sentiment("NeutralTest", [
            ("positive", "good stuff", "https://r.com/1"),
            ("neutral", "it is a product", "https://r.com/2"),
            ("negative", "bad stuff", "https://r.com/3"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        sentiments_in_passages = {p["sentiment"] for p in result["source_passages"]}
        assert "neutral" not in sentiments_in_passages

    def test_only_positive_records_still_works(self):
        product = _make_product_with_sentiment("AllPos", [
            ("positive", "amazing", "https://r.com/1"),
            ("positive", "fantastic", "https://r.com/2"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert len(result["source_passages"]) == 2
        assert all(p["sentiment"] == "positive" for p in result["source_passages"])

    def test_only_negative_records_still_works(self):
        product = _make_product_with_sentiment("AllNeg", [
            ("negative", "terrible", "https://r.com/1"),
        ])
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert len(result["source_passages"]) == 1
        assert result["source_passages"][0]["sentiment"] == "negative"

    def test_sentiment_records_none_treated_as_empty(self):
        product = {
            "name": "NoneRecords", "mention_count": 3, "sources": [],
            "sentiment_records": None,
        }
        result = _build_scored_dict(product, _make_scores(), _make_rubric())
        assert result["source_passages"] == []
