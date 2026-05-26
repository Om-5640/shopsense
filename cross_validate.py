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
from typing import Any

from agents import run_agent


def _majority_sentiment(sentiments: list[str]) -> str:
    counts = {"positive": 0, "negative": 0, "mixed": 0}
    for s in sentiments:
        normalized = s.lower() if s.lower() in counts else "mixed"
        counts[normalized] += 1
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _sentiments_are_split(by_subreddit: dict[str, list[str]]) -> bool:
    """
    Returns True if subreddits disagree on majority sentiment for a product.
    Only fires when there are 2+ subreddits with 1+ mention each.
    """
    majorities = set()
    for sub, sents in by_subreddit.items():
        if sents:
            majorities.add(_majority_sentiment(sents))
    return len(majorities) >= 2


def _call_cross_validator(product_name: str, by_subreddit: dict[str, list[str]]) -> dict[str, Any]:
    """
    Ask the cross_validator LLM to produce a structured explanation of why
    community sentiment differs for this product.
    """
    lines = [
        f"Product: {product_name}",
        "",
        "Sentiment by subreddit:",
    ]
    for sub, sents in by_subreddit.items():
        majority = _majority_sentiment(sents)
        lines.append(f"  r/{sub}: {majority} ({len(sents)} mentions)")

    prompt = "\n".join(lines) + """

Analyze why the sentiment differs across these communities. Consider:
- Use-case differences (e.g., gaming vs audiophile vs casual use)
- Price/value perception differences by community
- Brand loyalty or bias in specific communities
- Different feature priorities

Return JSON:
{
  "signal": "split",
  "explanation": "1-2 sentences summarizing the disagreement",
  "context_note": "Why a buyer should care about this split"
}"""

    try:
        raw = run_agent("cross_validator", user_prompt=prompt)
        from llm_client import safe_json_loads
        return safe_json_loads(raw)
    except Exception as exc:
        print(f"[cross_validate] LLM call failed for {product_name}: {exc}")
        return {
            "signal": "split",
            "explanation": f"Sentiment differs across communities.",
            "context_note": "Check individual subreddit discussions for details.",
        }


def annotate_cross_subreddit(
    analysis: dict,
    thread_summaries: list[dict],
    reddit_threads: list[dict],
) -> dict:
    """
    Walk through analysis.products and add `cross_subreddit_signal` to each.

    Inputs:
      analysis        — output of analyze_with_summaries (has products[])
      thread_summaries — list of structured summaries (has products_mentioned[])
      reddit_threads  — raw thread dicts (has subreddit field)

    Returns the analysis dict with cross_subreddit_signal added in-place.
    """
    products = analysis.get("products", [])
    if not products:
        return analysis

    # Build product → {subreddit: [sentiment, ...]} from thread summaries
    # We match thread_summaries[i] to reddit_threads[i] by position
    product_by_sub: dict[str, dict[str, list[str]]] = {}

    for i, summary in enumerate(thread_summaries):
        subreddit = ""
        if i < len(reddit_threads):
            subreddit = reddit_threads[i].get("subreddit", "") or ""
        if not subreddit:
            continue

        for pm in summary.get("products_mentioned", []):
            name = (pm.get("name") or "").strip()
            sentiment = (pm.get("sentiment") or "mixed").lower()
            if not name:
                continue
            if name not in product_by_sub:
                product_by_sub[name] = {}
            sub_key = subreddit.lower()
            if sub_key not in product_by_sub[name]:
                product_by_sub[name][sub_key] = []
            product_by_sub[name][sub_key].append(sentiment)

    for product in products:
        pname = product.get("name", "")

        # Try to find a match in product_by_sub (fuzzy: check if any key starts with first word)
        match_key = None
        pname_lower = pname.lower()
        for key in product_by_sub:
            if key.lower() == pname_lower or pname_lower.startswith(key.lower()[:6]):
                match_key = key
                break

        by_sub = product_by_sub.get(match_key or pname, {})
        n_subs = len(by_sub)

        if n_subs < 2:
            product["cross_subreddit_signal"] = {
                "signal": "single_source",
                "explanation": "",
                "context_note": "",
            }
        elif _sentiments_are_split(by_sub):
            product["cross_subreddit_signal"] = _call_cross_validator(pname, by_sub)
        else:
            # Multiple subreddits, all agree
            majority = _majority_sentiment(
                [s for sents in by_sub.values() for s in sents]
            )
            product["cross_subreddit_signal"] = {
                "signal": "consistent",
                "explanation": f"Consistently {majority} sentiment across {n_subs} communities.",
                "context_note": "",
            }

    return analysis
