"""
Cross-subreddit validation for product sentiment.

After thread summarization, products may appear in discussions from multiple
subreddits. This module compares sentiment across communities and flags
products where communities meaningfully disagree — which often signals:
  - Use-case fit differences (r/budgetaudiophile vs r/IndianGaming)
  - Brand fanboy bias in one community
  - Feature trade-offs that different audiences weight differently

Result is attached to each product as `cross_subreddit_signal`:
  "consistent"    — same sentiment across all subreddits that mention it
  "split"         — meaningfully different sentiment; explanation provided
  "single_source" — only one subreddit mentions it; no cross-validation possible
"""

import json
import re
import time
import logging
from collections import defaultdict
from typing import Any

from agents import run_agent

_logger = logging.getLogger(__name__)

try:
    from llm_client import safe_json_loads as _safe_json_loads
except ImportError:
    def _safe_json_loads(raw: str) -> dict:  # type: ignore[misc]
        try:
            return json.loads(raw)
        except Exception:
            return {}

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_SPLIT_LLM_CALLS = 15   # cap: max products getting LLM cross-validation per request
_REQUIRED_KEYS = frozenset({"signal", "explanation", "context_note"})

# In-process explanation cache — (canonical_key, frozenset of (sub, majority)) → result
_EXPLANATION_CACHE: dict[tuple, dict] = {}

_SPLIT_FALLBACK: dict = {
    "signal": "split",
    "explanation": "Sentiment differs across communities.",
    "context_note": "Check individual subreddit discussions for details.",
    "_is_fallback": True,   # distinguishes real results from error placeholders
}

# ── LLM prompt ────────────────────────────────────────────────────────────────

_BATCH_SYSTEM = """You are a product community sentiment analyst.

For each product listed, explain why its communities disagree about it.

Return ONLY valid JSON (no markdown):
{
  "Product Name": {
    "signal": "split",
    "explanation": "<1-2 sentences: specific reason — use-case fit / price-tier / brand bias / feature trade-off>",
    "context_note": "<1 sentence: actionable advice for a buyer>"
  }
}

Rules:
- signal: always exactly "split"
- explanation: name the specific reason; never write generic text like "communities disagree"
- context_note: what a buyer deciding on this product should know
- Include ALL listed products — no omissions
- JSON only, no markdown, no extra keys"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _canonical_key(name: str) -> str:
    """Strip punctuation/spaces/case — mirrors analysis_normalizer._canonical_key."""
    return re.sub(r"[\W_]", "", name.lower())


def _majority_sentiment(sentiments: list[str]) -> str:
    """
    Most frequent sentiment.
    Tie-break order: positive > negative > mixed — prefer higher-signal labels
    over "mixed" when counts are equal.
    """
    counts: dict[str, int] = {"positive": 0, "negative": 0, "mixed": 0}
    for s in sentiments:
        key = s.lower() if s.lower() in counts else "mixed"
        counts[key] += 1
    order = ["positive", "negative", "mixed"]
    return max(order, key=lambda k: (counts[k], -order.index(k)))


def _sentiments_are_split(by_subreddit: dict[str, list[str]]) -> bool:
    """
    True only when at least one subreddit is majority-positive AND another is
    majority-negative. Mixed-only divergence does not constitute a split —
    that would fire expensive LLM calls on ambiguous low-signal data.
    """
    majorities = {_majority_sentiment(sents) for sents in by_subreddit.values() if sents}
    return "positive" in majorities and "negative" in majorities


def _make_cache_key(product_name: str, by_subreddit: dict[str, list[str]]) -> tuple:
    sub_majorities = frozenset(
        (sub, _majority_sentiment(sents))
        for sub, sents in by_subreddit.items()
        if sents
    )
    return (_canonical_key(product_name), sub_majorities)


def _validate_result(result: Any) -> dict | None:
    """Return cleaned result dict if schema is valid, None otherwise."""
    if not isinstance(result, dict):
        return None
    if not _REQUIRED_KEYS.issubset(result.keys()):
        _logger.debug("[cross_validate] LLM result missing required keys: %s", result)
        return None
    if result.get("signal") not in {"split", "consistent", "single_source"}:
        result["signal"] = "split"
    return result


# ── Batch LLM call ────────────────────────────────────────────────────────────

def _call_batch_cross_validator(
    split_products: list[tuple[str, dict[str, list[str]]]],
) -> dict[str, dict]:
    """
    Single LLM call for ALL split products. Retries up to 2× with back-off.
    Returns {product_name: result_dict} — empty dict on total failure.
    """
    blocks = []
    for name, by_sub in split_products:
        sub_lines = "\n".join(
            f"  r/{sub}: {_majority_sentiment(sents)} ({len(sents)} mentions)"
            for sub, sents in sorted(by_sub.items())
            if sents
        )
        blocks.append(f"PRODUCT: {name}\n{sub_lines}")

    prompt = (
        "PRODUCTS WITH COMMUNITY DISAGREEMENT:\n\n"
        + "\n\n".join(blocks)
        + "\n\nReturn one JSON entry per product above."
    )

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            raw = run_agent("cross_validator", user_prompt=prompt, system=_BATCH_SYSTEM)
            parsed = _safe_json_loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))

    _logger.warning("[cross_validate] Batch LLM call failed after 3 attempts: %s", last_exc)
    return {}


# ── Main entry point ──────────────────────────────────────────────────────────

def annotate_cross_subreddit(
    analysis: dict,
    thread_summaries: list[dict],
    reddit_threads: list[dict],
) -> dict:
    """
    Walk through analysis.products and add `cross_subreddit_signal` to each.

    Inputs:
      analysis         — output of analyze_with_summaries (has products[])
      thread_summaries — list of structured summaries (has products_mentioned[])
      reddit_threads   — raw thread dicts (has subreddit field)

    Returns the analysis dict with cross_subreddit_signal added in-place.
    """
    products = analysis.get("products", [])
    if not products:
        return analysis

    # ── 1. Build product → {subreddit: [sentiment, ...]} ─────────────────────
    # Uses canonical keys to prevent case/punctuation fragmentation
    # (e.g. "iPhone 15", "Apple iPhone 15", "iphone15" all resolve to the same key).
    # Prefers URL-based thread matching over positional to survive reordering/filtering.

    url_to_subreddit: dict[str, str] = {
        t["url"]: t["subreddit"]
        for t in reddit_threads
        if t.get("url") and t.get("subreddit")
    }

    product_by_sub: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for i, summary in enumerate(thread_summaries):
        # URL match first — survives list reordering or partial failures
        thread_url = summary.get("url") or summary.get("thread_url", "")
        subreddit = url_to_subreddit.get(thread_url, "")
        # Positional fallback — only when URL is unavailable on both sides
        if not subreddit and i < len(reddit_threads):
            subreddit = (reddit_threads[i].get("subreddit") or "").strip()
        if not subreddit:
            continue

        sub_key = subreddit.lower()
        for pm in summary.get("products_mentioned", []):
            name = (pm.get("name") or "").strip()
            if not name:
                continue
            raw_sent = (pm.get("sentiment") or "mixed").lower().strip()
            sentiment = raw_sent if raw_sent in {"positive", "negative", "mixed"} else "mixed"
            product_by_sub[_canonical_key(name)][sub_key].append(sentiment)

    # ── 2. Classify each analysis product ────────────────────────────────────

    product_ckeys = [_canonical_key(p.get("name", "")) for p in products]
    signals: dict[str, dict] = {}
    split_needed: list[tuple[str, str, dict[str, list[str]]]] = []  # (ckey, name, by_sub)

    for ckey, product in zip(product_ckeys, products):
        pname = product.get("name", "")
        by_sub = dict(product_by_sub.get(ckey, {}))

        n_subs = len(by_sub)
        total_mentions = sum(len(sents) for sents in by_sub.values())

        if n_subs < 2 or total_mentions < 3:
            signals[ckey] = {"signal": "single_source", "explanation": "", "context_note": ""}
        elif _sentiments_are_split(by_sub):
            ck = _make_cache_key(pname, by_sub)
            if ck in _EXPLANATION_CACHE:
                _logger.debug("[cross_validate] Cache hit for %r", pname)
                signals[ckey] = _EXPLANATION_CACHE[ck]
            else:
                split_needed.append((ckey, pname, by_sub))
        else:
            majority = _majority_sentiment([s for sents in by_sub.values() for s in sents])
            signals[ckey] = {
                "signal": "consistent",
                "explanation": f"Consistently {majority} across {n_subs} communities.",
                "context_note": "",
            }

    # ── 3. Batch LLM call for all split products (capped) ────────────────────

    if split_needed:
        capped = split_needed[:MAX_SPLIT_LLM_CALLS]
        if len(split_needed) > MAX_SPLIT_LLM_CALLS:
            _logger.warning(
                "[cross_validate] %d split products; LLM limited to top %d",
                len(split_needed), MAX_SPLIT_LLM_CALLS,
            )

        batch_results = _call_batch_cross_validator(
            [(name, by_sub) for _, name, by_sub in capped]
        )

        for ckey, pname, by_sub in capped:
            ck = _make_cache_key(pname, by_sub)
            # Exact name match first; canonical key fallback handles capitalisation drift
            raw_result = batch_results.get(pname)
            if raw_result is None:
                for k, v in batch_results.items():
                    if _canonical_key(k) == ckey:
                        raw_result = v
                        break

            validated = _validate_result(raw_result) if raw_result is not None else None
            result = validated if validated is not None else dict(_SPLIT_FALLBACK)
            _EXPLANATION_CACHE[ck] = result
            signals[ckey] = result

        # Products beyond the cap get the fallback placeholder
        for ckey, _, _ in split_needed[MAX_SPLIT_LLM_CALLS:]:
            signals[ckey] = dict(_SPLIT_FALLBACK)

    # ── 4. Attach signals to products ────────────────────────────────────────

    for ckey, product in zip(product_ckeys, products):
        product["cross_subreddit_signal"] = signals.get(
            ckey,
            {"signal": "single_source", "explanation": "", "context_note": ""},
        )

    return analysis
