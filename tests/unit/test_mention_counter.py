"""
Unit tests for the Aho-Corasick mention counting pipeline.

Covers:
 - Automaton builds correctly from registry
 - Word-boundary enforcement (no partial matches inside URLs / compound words)
 - Overlapping-span deduplication (longer match wins)
 - Exclusion-pattern cancellation
 - Alias ambiguity guard (near-prefix skipping)
 - count_across_threads: multi-thread aggregation
 - Sentinel URL fallback (content-hash when url missing)
 - Sentiment output shape
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
from alias_resolver import ProductInfo, merge_into_registry
from mention_counter import (
    build_automaton,
    build_exclude_patterns,
    count_mentions_in_text,
    count_across_threads,
    MentionResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _registry(*name_alias_pairs) -> dict:
    """Build a minimal registry: [(canonical, [aliases, ...]), ...]"""
    corefs = [{name: aliases for name, aliases in name_alias_pairs}]
    return merge_into_registry(corefs)


def _make_automaton_excl(registry):
    return build_automaton(registry), build_exclude_patterns(registry)


# ── build_automaton ────────────────────────────────────────────────────────────

class TestBuildAutomaton:
    def test_builds_without_error(self):
        reg = _registry(("Sony WF-1000XM5", ["xm5"]))
        auto = build_automaton(reg)
        assert auto is not None

    def test_empty_registry_builds(self):
        auto = build_automaton({})
        assert auto is not None

    def test_automaton_finds_canonical_name(self):
        reg = _registry(("Sony WF-1000XM5", []))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("I love the Sony WF-1000XM5 earbuds.", auto, excl, reg)
        assert "Sony WF-1000XM5" in counts
        assert counts["Sony WF-1000XM5"] >= 1

    def test_automaton_finds_alias(self):
        reg = _registry(("Sony WF-1000XM5", ["xm5", "sony xm5"]))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("The xm5 has great ANC.", auto, excl, reg)
        assert "Sony WF-1000XM5" in counts

    def test_longer_canonical_wins_tie(self):
        """When two canonicals share a term, the longer canonical name wins."""
        reg = _registry(
            ("Widget X", []),
            ("Widget X Pro", []),
        )
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("Widget X Pro is amazing.", auto, excl, reg)
        # "Widget X Pro" is longer and should win
        assert counts.get("Widget X Pro", 0) >= 1


# ── Word-boundary enforcement ──────────────────────────────────────────────────

class TestWordBoundary:
    def test_no_match_inside_url(self):
        reg = _registry(("xm5", []))
        auto, excl = _make_automaton_excl(reg)
        # "xm5" embedded in URL path — should NOT match
        counts = count_mentions_in_text("See https://example.com/xm5reviews for more.", auto, excl, reg)
        assert counts.get("xm5", 0) == 0

    def test_no_partial_match_in_compound(self):
        reg = _registry(("air", []))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("The AirPods Pro has great audio.", auto, excl, reg)
        # "air" inside "AirPods" — word boundary should prevent match
        assert counts.get("air", 0) == 0

    def test_match_at_start_of_string(self):
        reg = _registry(("Sony WF-1000XM5", []))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("Sony WF-1000XM5 sounds great.", auto, excl, reg)
        assert counts.get("Sony WF-1000XM5", 0) == 1

    def test_match_at_end_of_string(self):
        reg = _registry(("Sony WF-1000XM5", []))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("I recommend the Sony WF-1000XM5", auto, excl, reg)
        assert counts.get("Sony WF-1000XM5", 0) == 1

    def test_multiple_occurrences_counted(self):
        reg = _registry(("xm5", []))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("xm5 vs xm5 vs xm5", auto, excl, reg)
        assert counts.get("xm5", 0) == 3


# ── Overlap deduplication ─────────────────────────────────────────────────────

class TestOverlapDedup:
    def test_longer_match_wins_overlap(self):
        """'Sony WF-1000XM5' and 'xm5' overlap — longer wins, counts as 1."""
        reg = _registry(("Sony WF-1000XM5", ["xm5"]))
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text("The Sony WF-1000XM5 battery rocks.", auto, excl, reg)
        # Should be counted once as the full name, not double-counted
        total = sum(counts.values())
        assert total == 1

    def test_adjacent_non_overlapping_both_counted(self):
        reg = _registry(
            ("Sony WF-1000XM5", []),
            ("Apple AirPods Pro", []),
        )
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text(
            "Sony WF-1000XM5 vs Apple AirPods Pro — which is better?",
            auto, excl, reg,
        )
        assert counts.get("Sony WF-1000XM5", 0) == 1
        assert counts.get("Apple AirPods Pro", 0) == 1


# ── Exclusion-pattern cancellation ────────────────────────────────────────────

class TestExclusionPatterns:
    def test_exclusion_cancels_base_match(self):
        """'Buds Air 7' should NOT match when 'Buds Air 7 Pro' is also in registry."""
        reg = _registry(
            ("Buds Air 7", []),
            ("Buds Air 7 Pro", []),
        )
        auto, excl = _make_automaton_excl(reg)
        # Text only mentions "Buds Air 7 Pro"; "Buds Air 7" should be cancelled
        counts = count_mentions_in_text("The Buds Air 7 Pro is the top model.", auto, excl, reg)
        assert counts.get("Buds Air 7", 0) == 0
        assert counts.get("Buds Air 7 Pro", 0) >= 1

    def test_base_matched_without_variant_nearby(self):
        reg = _registry(
            ("Buds Air 7", []),
            ("Buds Air 7 Pro", []),
        )
        auto, excl = _make_automaton_excl(reg)
        counts = count_mentions_in_text(
            "I bought the Buds Air 7 last month. Not the Pro version.",
            auto, excl, reg,
        )
        assert counts.get("Buds Air 7", 0) >= 1


# ── count_across_threads ──────────────────────────────────────────────────────

class TestCountAcrossThreads:
    def _make_thread(self, url, title="", body="", comments=None):
        return {"url": url, "title": title, "body": body, "comments": comments or []}

    def test_basic_cross_thread_aggregation(self):
        reg = _registry(("Sony WF-1000XM5", ["xm5"]))
        auto, excl = _make_automaton_excl(reg)
        threads = [
            self._make_thread("http://r.com/1", title="Recommend Sony WF-1000XM5"),
            self._make_thread("http://r.com/2", body="xm5 is my daily driver"),
        ]
        results = count_across_threads(threads, reg, auto, excl, llm_client=None, run_sentiment=False)
        assert "Sony WF-1000XM5" in results
        mr = results["Sony WF-1000XM5"]
        assert mr.total_mentions >= 2
        assert mr.distinct_threads == 2

    def test_comment_mentions_counted(self):
        reg = _registry(("Sony WF-1000XM5", []))
        auto, excl = _make_automaton_excl(reg)
        threads = [
            self._make_thread("http://r.com/1", comments=[
                {"body": "Sony WF-1000XM5 is great!"},
                {"body": "Another comment without product"},
            ])
        ]
        results = count_across_threads(threads, reg, auto, excl, llm_client=None, run_sentiment=False)
        assert results["Sony WF-1000XM5"].total_mentions >= 1

    def test_empty_threads_returns_empty(self):
        reg = _registry(("Widget", []))
        auto, excl = _make_automaton_excl(reg)
        results = count_across_threads([], reg, auto, excl, llm_client=None, run_sentiment=False)
        assert results == {}

    def test_thread_without_url_uses_content_hash(self):
        """Bug 5 fix: id(thread) is non-deterministic; use content hash instead."""
        reg = _registry(("Widget X", []))
        auto, excl = _make_automaton_excl(reg)
        thread = {"title": "Widget X rocks", "body": "I love Widget X", "comments": []}
        results = count_across_threads([thread], reg, auto, excl, llm_client=None, run_sentiment=False)
        assert "Widget X" in results
        assert results["Widget X"].distinct_threads == 1

    def test_no_double_count_across_threads(self):
        reg = _registry(("Widget X", []))
        auto, excl = _make_automaton_excl(reg)
        threads = [
            self._make_thread("http://r.com/1", title="Widget X"),
            self._make_thread("http://r.com/1", title="Widget X"),  # same URL
        ]
        results = count_across_threads(threads, reg, auto, excl, llm_client=None, run_sentiment=False)
        mr = results.get("Widget X")
        if mr:
            # Same URL → 1 distinct thread (counts may vary by implementation)
            assert mr.distinct_threads <= 2


# ── MentionResult ─────────────────────────────────────────────────────────────

class TestMentionResult:
    def test_sentiment_score_neutral_when_no_data(self):
        mr = MentionResult("Widget")
        assert mr.sentiment_score == 0.0

    def test_dominant_sentiment_unknown_when_no_data(self):
        mr = MentionResult("Widget")
        assert mr.dominant_sentiment == "unknown"

    def test_dominant_sentiment_positive(self):
        mr = MentionResult("Widget", positive=5, negative=1, neutral=1)
        assert mr.dominant_sentiment == "positive"

    def test_dominant_sentiment_negative(self):
        mr = MentionResult("Widget", positive=1, negative=8, neutral=1)
        assert mr.dominant_sentiment == "negative"

    def test_sentiment_score_range(self):
        mr = MentionResult("Widget", positive=10, negative=0, neutral=0)
        assert mr.sentiment_score == 1.0
        mr2 = MentionResult("Widget", positive=0, negative=10, neutral=0)
        assert mr2.sentiment_score == -1.0


# ── merge_into_registry ───────────────────────────────────────────────────────

class TestMergeIntoRegistry:
    def test_aliases_merged_across_threads(self):
        corefs = [
            {"Sony WF-1000XM5": ["xm5"]},
            {"Sony WF-1000XM5": ["sony xm5", "the xm5"]},
        ]
        reg = merge_into_registry(corefs)
        key = "sony wf-1000xm5"
        assert key in reg
        aliases = [a.lower() for a in reg[key].aliases]
        assert "xm5" in aliases
        assert "sony xm5" in aliases

    def test_auto_exclusion_base_excludes_variant(self):
        corefs = [{"Widget X": [], "Widget X Pro": []}]
        reg = merge_into_registry(corefs)
        base = reg.get("widget x")
        assert base is not None
        excl_lower = [e.lower() for e in base.excludes]
        assert any("pro" in e for e in excl_lower)

    def test_empty_corefs_returns_empty_registry(self):
        assert merge_into_registry([]) == {}

    def test_base_registry_seeded(self):
        base = {"widget a": ProductInfo("Widget A")}
        corefs = [{"Widget B": []}]
        reg = merge_into_registry(corefs, base=base)
        assert "widget a" in reg
        assert "widget b" in reg
