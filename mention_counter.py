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

import hashlib
import json
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Import thread-level batch function — one LLM call per thread, not per comment
try:
    from sentiment_analyser import analyse_thread_comments as _analyse_thread_comments
    _HAS_SENTIMENT = True
except ImportError:
    _analyse_thread_comments = None  # type: ignore[assignment]
    _HAS_SENTIMENT = False


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
        # Bug 1: when no sentiment data exists, max() on all-zeros returns the
        # first key ("positive") — wrong.  Return "unknown" instead.
        total = self.positive + self.negative + self.neutral
        if total == 0:
            return "unknown"
        counts = {"positive": self.positive, "negative": self.negative, "neutral": self.neutral}
        return max(counts, key=counts.__getitem__)


# ── Automaton builder ──────────────────────────────────────────────────────────

def build_automaton(registry: dict) -> object:
    """
    Build an Aho-Corasick automaton from the registry.

    Payload per entry: (canonical_name, matched_term)
    Conflict resolution when two canonicals share a lowercase term:
      - Longer canonical wins (more specific)
      - Equal-length: first-seen wins (stable); warning logged (Bug 2)
    Alias overlap: aliases that are a near-prefix of another canonical name
    (length diff < 3) are skipped to prevent ambiguous cross-product matches.

    Returns a ready-to-use ahocorasick.Automaton.
    """
    import ahocorasick

    A = ahocorasick.Automaton()

    # term_lower → (canonical_name, original_term)
    term_map: dict[str, tuple[str, str]] = {}

    # Pre-collect all canonical names (lowercase) for alias overlap checks
    all_canonicals_lower = {info.canonical_name.lower() for info in registry.values()}

    for key, info in registry.items():
        canonical = info.canonical_name

        for term in [canonical] + info.aliases:
            term_lower = term.lower().strip()
            if not term_lower:
                continue

            # Alias overlap bug: if an alias is a prefix of another canonical
            # name and the length difference is < 3, it is too ambiguous to be
            # useful — skip it and warn the registry author.
            if term_lower != canonical.lower():
                ambiguous = False
                for other_lower in all_canonicals_lower:
                    if other_lower == canonical.lower():
                        continue
                    if (other_lower.startswith(term_lower)
                            and len(other_lower) - len(term_lower) < 3):
                        logger.warning(
                            "[mention_counter] Alias '%s' (→ '%s') is a near-prefix of canonical "
                            "'%s' (diff=%d chars) — skipping to avoid ambiguous matches",
                            term_lower, canonical, other_lower,
                            len(other_lower) - len(term_lower),
                        )
                        ambiguous = True
                        break
                if ambiguous:
                    continue

            existing = term_map.get(term_lower)
            if existing is None or len(canonical) > len(existing[0]):
                term_map[term_lower] = (canonical, term)
            elif len(canonical) == len(existing[0]) and canonical != existing[0]:
                # Bug 2: equal-length tie — first-seen wins for stability; log so
                # registry authors can detect and resolve the conflict explicitly.
                logger.warning(
                    "[mention_counter] Ambiguous alias '%s' maps to both '%s' and '%s' "
                    "— keeping '%s'",
                    term_lower, existing[0], canonical, existing[0],
                )

    for term_lower, (canonical, original) in term_map.items():
        A.add_word(term_lower, (canonical, original))

    A.make_automaton()
    return A


def build_exclude_patterns(registry: dict) -> dict[str, re.Pattern]:
    """
    Pre-compile exclusion patterns from registry.excludes.

    Optimization 2: combines all exclusions for a canonical into a single
    compiled alternation regex — one .search() per match instead of N.

    Returns { canonical_name: combined_pattern }
    """
    patterns: dict[str, re.Pattern] = {}

    for key, info in registry.items():
        if not info.excludes:
            continue
        parts = [
            re.escape(e.lower())
            for e in sorted(info.excludes, key=len, reverse=True)
            if e
        ]
        if not parts:
            continue
        try:
            patterns[info.canonical_name] = re.compile("|".join(parts))
        except re.error as exc:
            logger.warning(
                "[mention_counter] Could not compile exclusion pattern for '%s': %s",
                info.canonical_name, exc,
            )

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
    exclude_patterns: dict[str, re.Pattern],
    registry: dict,
) -> dict[str, int]:
    """
    Run Aho-Corasick over `text` and return {canonical_name: count}.

    Steps:
      1. Lowercase the text (automaton keys are lowercase)
      2. Single O(n) pass collecting all matches as (start, end, canonical, term)
      3. Enforce word boundaries — drop matches that aren't on word boundaries
      4. Deduplicate overlapping spans — longer match wins at any character position
         Opt 1: interval list replaces position set — avoids O(span_len) allocations
      5. For each confirmed match check exclusion pattern in a 30-char window
         Opt 2: single combined regex, one .search() call per match
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

    # Opt 1: track accepted intervals as (start, end) pairs instead of a position
    # set.  Avoids allocating set(range(start, end)) — O(span_length) — per match.
    # Linear overlap check is O(accepted_count) which stays small in practice.
    accepted: list[tuple[int, int]] = []
    deduped: list[tuple[int, int, str, str]] = []

    for start, end, canonical, term in raw_matches:
        if any(start < a_end and end > a_start for a_start, a_end in accepted):
            continue
        accepted.append((start, end))
        deduped.append((start, end, canonical, term))

    # Exclusion pass — Opt 2: single .search() per match via combined regex
    counts: dict[str, int] = {}

    for start, end, canonical, term in deduped:
        excl_pat = exclude_patterns.get(canonical)
        cancelled = False
        if excl_pat:
            window_start = max(0, start - 30)
            window_end = min(len(text_lower), end + 30)
            cancelled = bool(excl_pat.search(text_lower[window_start:window_end]))

        if not cancelled:
            counts[canonical] = counts.get(canonical, 0) + 1

    return counts


# ── Cross-thread aggregator ────────────────────────────────────────────────────

def count_across_threads(
    threads: list[dict],
    registry: dict,
    automaton,
    exclude_patterns: dict[str, re.Pattern],
    llm_client=None,
    run_sentiment: bool = True,
) -> dict[str, "MentionResult"]:
    """
    Count product mentions across all threads and score per-thread sentiment.

    Counting strategy:
      - Title and body: counted at thread level (pure Aho-Corasick, no LLM)
      - Each comment: counted individually; products noted for batch sentiment

    Sentiment strategy (changed from per-comment to per-thread batch):
      - Rule-based pre-pass handles strong signals (0 LLM calls for those)
      - ONE batched LLM call per thread for remaining ambiguous comments
      - Max ~15 LLM calls for sentiment across a full 15-thread search
        (previously up to 50 per-comment calls)

    Returns { canonical_name: MentionResult }
    """
    results: dict[str, MentionResult] = {}

    for thread in threads:
        # Bug 5: stable URL fallback using content hash — id(thread) is a memory
        # address that changes every run, breaking any dedup/cache keyed on thread_url.
        thread_url = thread.get("url") or (
            "thread_" + hashlib.md5(
                json.dumps(
                    {"t": thread.get("title", ""), "b": (thread.get("body") or "")[:100]},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:12]
        )

        # ── Title + body mention counting ─────────────────────────────────────
        title_counts = count_mentions_in_text(
            thread.get("title", ""), automaton, exclude_patterns, registry
        )
        body_counts = count_mentions_in_text(
            thread.get("body", ""), automaton, exclude_patterns, registry
        )

        thread_counts: dict[str, int] = {}
        for counts in (title_counts, body_counts):
            for canonical, cnt in counts.items():
                thread_counts[canonical] = thread_counts.get(canonical, 0) + cnt

        for canonical, cnt in thread_counts.items():
            mr = results.setdefault(canonical, MentionResult(canonical_name=canonical))
            mr.total_mentions += cnt
            if thread_url not in mr.per_thread:
                mr.per_thread[thread_url] = 0
                mr.distinct_threads += 1
            mr.per_thread[thread_url] += cnt

        # ── Per-comment counting — collect sentiment inputs for batch call ────
        # sentiment_inputs: (comment_body, products_in_comment) for each comment
        # that has at least one confirmed product mention.
        sentiment_inputs: list[tuple[str, list[str]]] = []

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
                mr = results.setdefault(canonical, MentionResult(canonical_name=canonical))
                mr.total_mentions += cnt
                mr.distinct_comments += 1
                if thread_url not in mr.per_thread:
                    mr.per_thread[thread_url] = 0
                    mr.distinct_threads += 1
                mr.per_thread[thread_url] += cnt

            if run_sentiment and llm_client is not None and _HAS_SENTIMENT:
                sentiment_inputs.append((comment_body, products_in_comment))

        # ── One batched sentiment call for the whole thread ───────────────────
        if sentiment_inputs:
            try:
                sentiment_maps = _analyse_thread_comments(sentiment_inputs, llm_client)
                for (comment_body, _), sentiment_map in zip(sentiment_inputs, sentiment_maps):
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
                            "source": score_obj.source,
                        })
            except Exception as exc:
                logger.warning("[mention_counter] thread-level sentiment batch failed: %s", exc)

    return results
