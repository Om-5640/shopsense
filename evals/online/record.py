"""
Online recorder — runs the real pipeline on the fixed query set and captures the output as
recorded fixtures, then scores them with the real online-quality metrics.

Run:  python -m evals.online.record

Hard-capped at MAX_ONLINE_QUERIES (2) to respect free-tier rate limits. Each captured fixture
is written to evals/data/fixtures/recorded/<slug>.json and is then replayed deterministically
(and for free) by CI via tests/evals/test_recorded_pipeline.py and the full eval.

This is the bridge between "we have a benchmark" and "the benchmark measures real AI output":
the synthetic suite proves the scoring math; these fixtures prove the live model still extracts
the right products with grounded evidence.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from evals.online import ONLINE_QUERIES, MAX_ONLINE_QUERIES

_RECORDED_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "recorded"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def _run_one(query: str, category_hint: str, region: str) -> dict | None:
    """Drive the real pipeline non-interactively (no interview) and return a recorded fixture."""
    from category import resolve_category_interactively
    from criteria import generate_criteria
    from rubric import generate_rubric, fill_criterion_gaps
    from reddit_fetch import fetch_all_threads, set_session_region
    from review_fetch import fetch_all_reviews
    from normalizer import normalize_all
    from thread_summarizer import summarize_threads_parallel
    from llm_client import analyze_with_summaries
    from scorer import score_all_products

    print(f"\n=== recording: {query!r} ===")
    cat = resolve_category_interactively(query, forced_category=category_hint)["category"]
    set_session_region(region)

    criteria = generate_criteria(cat)
    profile = {"interview": [], "preferences_summary": "(online eval — default weights)", "region": region}
    rubric = generate_rubric(cat, criteria, profile)
    rubric["category"] = cat

    threads = fetch_all_threads(query, limit=12)
    reviews = fetch_all_reviews(query, limit=6)
    if not threads and not reviews:
        print("  no sources fetched — skipping")
        return None

    summaries = summarize_threads_parallel(threads, query)
    analysis = analyze_with_summaries(query, summaries, reviews)
    products = analysis.get("products", [])
    if not products:
        print("  no products extracted — skipping")
        return None

    sources = normalize_all(threads, reviews)
    research_text = "\n\n".join(s.get("text", "") for s in sources)[:40000]
    rubric = fill_criterion_gaps(rubric, cat, profile, research_text)
    scored = score_all_products(products, rubric, research_text)

    top_names = [p.get("name", "") for p in scored[:6] if p.get("name")]
    return {
        "_meta": {
            "query": query,
            "category": cat,
            "region": region,
            "captured_at": date.today().isoformat(),
            "note": "Auto-captured by `python -m evals.online.record`. Replayed deterministically in CI.",
            "source_excerpt": (analysis.get("summary") or "")[:1500],
            "expected_products": top_names[:4],
        },
        "scored_products": scored,
    }


def main() -> int:
    queries = ONLINE_QUERIES[:MAX_ONLINE_QUERIES]
    print(f"Online recorder — {len(queries)} real queries (capped at {MAX_ONLINE_QUERIES} for free-tier limits)")
    _RECORDED_DIR.mkdir(parents=True, exist_ok=True)

    captured = 0
    for q in queries:
        try:
            fixture = _run_one(q["query"], q.get("category"), q.get("region", "global"))
        except Exception as exc:
            print(f"  capture failed for {q['query']!r}: {exc}")
            continue
        if not fixture:
            continue
        out = _RECORDED_DIR / f"{_slug(q['query'])}.json"
        out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote {out.relative_to(_RECORDED_DIR.parent.parent.parent)}  "
              f"({len(fixture['scored_products'])} products)")
        captured += 1
        time.sleep(2)  # gentle spacing between runs

    if captured == 0:
        print("\nNo fixtures captured (check API keys / quota).")
        return 1

    # Score the freshly captured fixtures with the real online-quality metrics.
    from evals.benchmarks.recorded import load_recorded_pipeline_results
    from evals.metrics.retrieval_quality import RetrievalQualityMetric
    from evals.metrics.explanation_integrity import ExplanationIntegrityMetric

    pr = load_recorded_pipeline_results()
    rq = RetrievalQualityMetric().evaluate([], pipeline_results=pr)
    ei = ExplanationIntegrityMetric().evaluate([], pipeline_results=pr)
    print("\n--- online quality on recorded output ---")
    print(f"  retrieval_quality      {rq.score:.1f}/100  [{'PASS' if rq.passed else 'FAIL'}]")
    print(f"  explanation_integrity  {ei.score:.1f}/100  [{'PASS' if ei.passed else 'FAIL'}]")
    print(f"\nCaptured {captured} fixture(s). Commit them so CI replays real output for free.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
