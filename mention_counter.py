"""
Precise mention counter — Phase 2.

Uses pyahocorasick for O(n) multi-pattern scanning:
  - Matches ALL canonical names + aliases simultaneously in a single text pass
  - Word-boundary enforcement (no partial matches inside URLs or compound words)
  - Overlapping-span deduplication (longer match beats shorter at the same position)
  - Exclusion-pattern cancellation (prevents "Buds Air 7" counting inside "Buds Air 7 Pro")
  - Per-comment sentiment integration when run_sentiment=True
  - Returns deterministic integer counts — NOT LLM estimates
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class MentionResult:
    canonical_name: str
    total_mentions: int = 0
    distinct_threads: int = 0
    distinct_comments: int = 0
    per_thread: dict = field(default_factory=dict)       # thread_url → count
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    sentiment_records: list = field(default_factory=list)  # per-comment dicts

    @property
    def sentiment_score(self) -> float:
        """(positive - negative) / max(total, 1)  →  range -1.0 to +1.0"""
        total = self.positive + self.negative + self.neutral
        return (self.positive - self.negative) / max(total, 1)

    @property
    def dominant_sentiment(self) -> str:
        """Whichever of positive / negative / neutral has the highest count."""
        counts = {"positive": self.positive, "negative": self.negative, "neutral": self.neutral}
        return max(counts, key=counts.__getitem__)


# ── Automaton builder ──────────────────────────────────────────────────────────

def build_automaton(registry: dict) -> object:
    """
    Build an Aho-Corasick automaton from the registry.

    Payload per entry: (canonical_name, matched_term)
    If the same lowercase term maps to two canonicals, keep the longer
    (more specific) canonical so "Buds Air 7 Pro" beats "Buds Air 7".

    Returns a ready-to-use ahocorasick.Automaton.
    """
    import ahocorasick

    A = ahocorasick.Automaton()

    # term_lower → (canonical_name, original_term)
    # Resolve conflicts: longer canonical wins
    term_map: dict[str, tuple[str, str]] = {}

    for key, info in registry.items():
        canonical = info.canonical_name

        # Register the canonical name itself
        for term in [canonical] + info.aliases:
            term_lower = term.lower().strip()
            if not term_lower:
                continue
            existing = term_map.get(term_lower)
            if existing is None or len(canonical) > len(existing[0]):
                term_map[term_lower] = (canonical, term)

    for term_lower, (canonical, original) in term_map.items():
        A.add_word(term_lower, (canonical, original))

    A.make_automaton()
    return A


def build_exclude_patterns(registry: dict) -> dict[str, list]:
    """
    Pre-compile exclusion regexes from registry.excludes.

    Returns { canonical_name: [compiled_regex, ...] } sorted longest-first
    to prevent partial matches (e.g., "Pro 2" checked before "Pro").
    """
    patterns: dict[str, list] = {}

    for key, info in registry.items():
        if not info.excludes:
            continue
        compiled = []
        for excl in sorted(info.excludes, key=len, reverse=True):
            try:
                compiled.append(re.compile(re.escape(excl.lower())))
            except re.error:
                pass
        if compiled:
            patterns[info.canonical_name] = compiled

    return patterns


# ── Word-boundary helpers ─────────────────────────────────────────────────────

def _is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _has_word_boundary(text: str, start: int, end: int) -> bool:
    """
    Return True if the match at [start:end] sits on word boundaries.
    char before start must NOT be alphanumeric (or we're at string start).
    char after end must NOT be alphanumeric (or we're at string end).
    """
    if start > 0 and _is_word_char(text[start - 1]):
        return False
    if end < len(text) and _is_word_char(text[end]):
        return False
    return True


# ── Single-text mention counter ───────────────────────────────────────────────

def count_mentions_in_text(
    text: str,
    automaton,
    exclude_patterns: dict[str, list],
    registry: dict,
) -> dict[str, int]:
    """
    Run Aho-Corasick over `text` and return {canonical_name: count}.

    Steps:
      1. Lowercase the text (automaton keys are lowercase)
      2. Single O(n) pass collecting all matches as (start, end, canonical, term)
      3. Enforce word boundaries — drop matches that aren't on word boundaries
      4. Deduplicate overlapping spans — longer match wins at any character position
      5. For each confirmed match, check exclusion patterns in a 30-char window
      6. Return counts only for products with count > 0
    """
    if not text or not text.strip():
        return {}

    text_lower = text.lower()
    raw_matches: list[tuple[int, int, str, str]] = []  # (start, end, canonical, term)

    for end_idx, (canonical, original_term) in automaton.iter(text_lower):
        term_lower = original_term.lower()
        start_idx = end_idx - len(term_lower) + 1
        end_idx_excl = end_idx + 1  # exclusive

        if not _has_word_boundary(text_lower, start_idx, end_idx_excl):
            continue

        raw_matches.append((start_idx, end_idx_excl, canonical, term_lower))

    if not raw_matches:
        return {}

    # Sort by start, then by match length descending (longer first at same start)
    raw_matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))

    # Deduplicate overlapping spans: use a "covered positions" set.
    # For each match, if it introduces any character position already covered by
    # a LONGER match, skip it. If it's longer, it was sorted first, so it wins.
    covered: set[int] = set()
    deduped: list[tuple[int, int, str, str]] = []

    for start, end, canonical, term in raw_matches:
        span = set(range(start, end))
        if span & covered:
            # Overlap with an already-accepted longer match — skip
            continue
        covered |= span
        deduped.append((start, end, canonical, term))

    # Exclusion pass
    counts: dict[str, int] = {}
    excl_patterns = exclude_patterns  # shorthand

    for start, end, canonical, term in deduped:
        # Check if any exclusion pattern for this canonical appears within 30 chars around match
        excl_list = excl_patterns.get(canonical, [])
        cancelled = False
        if excl_list:
            window_start = max(0, start - 30)
            window_end = min(len(text_lower), end + 30)
            window = text_lower[window_start:window_end]
            for pat in excl_list:
                if pat.search(window):
                    cancelled = True
                    break

        if not cancelled:
            counts[canonical] = counts.get(canonical, 0) + 1

    return counts


# ── Cross-thread aggregator ────────────────────────────────────────────────────

def count_across_threads(
    threads: list[dict],
    registry: dict,
    automaton,
    exclude_patterns: dict,
    llm_client=None,
    run_sentiment: bool = True,
) -> dict[str, "MentionResult"]:
    """
    Count product mentions across all threads and optionally score per-comment sentiment.

    Counting strategy:
      - Title and body: counted at thread level (not per-comment sentiment)
      - Each comment: counted individually; sentiment scored if product found + run_sentiment=True

    LLM call budget:
      - 0 calls for title/body (pure Aho-Corasick)
      - 0 calls for comments with no product mention
      - 1 call per comment that contains ≥1 product mention (when run_sentiment=True)

    Returns { canonical_name: MentionResult }
    """
    results: dict[str, MentionResult] = {}

    def _get_or_create(canonical: str) -> MentionResult:
        if canonical not in results:
            results[canonical] = MentionResult(canonical_name=canonical)
        return results[canonical]

    for thread in threads:
        thread_url = thread.get("url", f"thread_{id(thread)}")

        # Count in title
        title_counts = count_mentions_in_text(
            thread.get("title", ""), automaton, exclude_patterns, registry
        )
        # Count in body
        body_counts = count_mentions_in_text(
            thread.get("body", ""), automaton, exclude_patterns, registry
        )

        # Merge title + body into thread-level counts
        thread_counts: dict[str, int] = {}
        for canonical, cnt in {**title_counts, **body_counts}.items():
            thread_counts[canonical] = thread_counts.get(canonical, 0) + cnt

        for canonical, cnt in thread_counts.items():
            mr = _get_or_create(canonical)
            mr.total_mentions += cnt
            if thread_url not in mr.per_thread:
                mr.per_thread[thread_url] = 0
                mr.distinct_threads += 1
            mr.per_thread[thread_url] += cnt

        # Per-comment counting + optional sentiment
        for comment in thread.get("comments", []):
            comment_body = (comment.get("body") or "").strip()
            if not comment_body:
                continue

            comment_counts = count_mentions_in_text(
                comment_body, automaton, exclude_patterns, registry
            )
            if not comment_counts:
                continue

            products_in_comment = list(comment_counts.keys())

            for canonical, cnt in comment_counts.items():
                mr = _get_or_create(canonical)
                mr.total_mentions += cnt
                mr.distinct_comments += 1
                if thread_url not in mr.per_thread:
                    mr.per_thread[thread_url] = 0
                    mr.distinct_threads += 1
                mr.per_thread[thread_url] += cnt

            # Sentiment analysis — only for comments that have confirmed mentions
            if run_sentiment and llm_client is not None:
                try:
                    from sentiment_analyser import analyse_comment
                    sentiment_map = analyse_comment(
                        comment_body, products_in_comment, llm_client
                    )
                    for canonical, score_obj in sentiment_map.items():
                        if canonical not in results:
                            continue
                        mr = results[canonical]
                        s = score_obj.sentiment
                        if s == "positive":
                            mr.positive += 1
                        elif s == "negative":
                            mr.negative += 1
                        else:
                            mr.neutral += 1

                        mr.sentiment_records.append({
                            "comment_text": comment_body[:300],
                            "sentiment": s,
                            "confidence": score_obj.confidence,
                            "reason": score_obj.reason,
                        })
                except Exception as exc:
                    logger.warning("[mention_counter] sentiment failed for comment: %s", exc)
                    # Neutral fallback already implicit — no increment needed

    return results
