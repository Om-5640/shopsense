"""
Mention pipeline — Phase 4 orchestrator.

Full pipeline:
  1. coref_pass per thread          (alias_resolver) — discovers aliases via LLM
  2. merge_into_registry            (alias_resolver) — unified ProductInfo registry
  3. build_automaton                (mention_counter) — O(1) build, O(n) scan
  4. build_exclude_patterns         (mention_counter) — pre-compile variant exclusions
  5. count_across_threads           (mention_counter) — deterministic counts + sentiment
  6. Sort by sentiment_score desc, then total_mentions desc

LLM call budget per search session:
  - 1 coref call per thread (alias discovery)
  - 1 sentiment call per comment that contains a confirmed product mention
  - 0 calls for title/body counting
  - 0 calls for comments with no product mention

Result: { canonical_name: MentionResult } sorted dict
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from alias_resolver import coref_pass, merge_into_registry
from mention_counter import build_automaton, build_exclude_patterns, count_across_threads

logger = logging.getLogger(__name__)


def run_pipeline(
    threads: list[dict],
    llm_client,
    base_registry: dict | None = None,
    run_sentiment: bool = True,
    pre_coref_maps: list[dict] | None = None,
) -> dict:
    """
    Run the full mention-counting + sentiment pipeline over raw Reddit threads.

    Args:
        threads       : list of raw thread dicts from reddit_fetch
                        each with keys: url, title, body, comments, subreddit
        llm_client    : callable matching run_agent(agent_name, user_prompt, system)
        base_registry : optional pre-seeded ProductInfo registry to extend
        run_sentiment : if True, run per-comment sentiment LLM calls

    Returns:
        Sorted dict { canonical_name: MentionResult }
        Sorted by: sentiment_score desc, then total_mentions desc.
        Empty dict on any unrecoverable error.
    """
    if not threads:
        logger.info("[mention_pipeline] no threads provided, returning empty result")
        return {}

    try:
        # ── Step 1: Per-thread coreference / alias resolution ─────────────────
        if pre_coref_maps is not None:
            # Fast path: aliases already extracted from thread summaries — zero LLM calls.
            # Truncate if more summaries than threads; pad with independent empty dicts
            # if fewer (extra raw threads are de-duplicates whose products are already
            # covered by base_registry).
            per_thread_corefs = list(pre_coref_maps)[:len(threads)]
            while len(per_thread_corefs) < len(threads):
                per_thread_corefs.append({})   # independent empty dict, not a shared ref
            logger.info(
                "[mention_pipeline] using %d pre-extracted alias maps from summaries (skipping coref_pass)",
                len(pre_coref_maps),
            )
        else:
            # Fallback: run coref_pass LLM calls in parallel (original behaviour)
            logger.info("[mention_pipeline] running coref_pass on %d threads (parallel)", len(threads))
            per_thread_corefs = [{} for _ in range(len(threads))]   # independent dicts (Bug 1 fix)
            with ThreadPoolExecutor(max_workers=5) as pool:
                future_to_idx = {
                    pool.submit(coref_pass, thread, llm_client): i
                    for i, thread in enumerate(threads)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        per_thread_corefs[idx] = future.result()
                    except Exception as exc:
                        logger.warning(
                            "[mention_pipeline] coref_pass failed for thread %d: %s", idx, exc
                        )
                        per_thread_corefs[idx] = {}

        coref_products_found = sum(len(c) for c in per_thread_corefs)
        logger.info("[mention_pipeline] coref found %d unique product names across threads",
                    coref_products_found)

        # ── Step 2: Build unified registry ────────────────────────────────────
        registry = merge_into_registry(per_thread_corefs, base=base_registry)
        logger.info("[mention_pipeline] registry has %d canonical products", len(registry))

        if not registry:
            logger.info("[mention_pipeline] empty registry — no products identified in threads")
            return {}

        # ── Step 3: Build Aho-Corasick automaton ──────────────────────────────
        automaton = build_automaton(registry)

        # ── Step 4: Build exclusion patterns ──────────────────────────────────
        exclude_patterns = build_exclude_patterns(registry)

        # ── Step 5: Count mentions + run sentiment ─────────────────────────────
        logger.info(
            "[mention_pipeline] counting mentions across %d threads (sentiment=%s)",
            len(threads), run_sentiment
        )
        results = count_across_threads(
            threads=threads,
            registry=registry,
            automaton=automaton,
            exclude_patterns=exclude_patterns,
            llm_client=llm_client if run_sentiment else None,
            run_sentiment=run_sentiment,
        )

        if not results:
            logger.info("[mention_pipeline] no mentions found in any thread")
            return {}

        # ── Step 6: Sort ───────────────────────────────────────────────────────
        sorted_items = sorted(
            results.items(),
            key=lambda item: (item[1].sentiment_score, item[1].total_mentions),
            reverse=True,
        )

        total_mentions = sum(mr.total_mentions for mr in results.values())
        total_sentiment_calls = sum(len(mr.sentiment_records) for mr in results.values())
        logger.info(
            "[mention_pipeline] done: %d products, %d total mentions, %d sentiment records",
            len(sorted_items), total_mentions, total_sentiment_calls
        )

        return dict(sorted_items)

    except Exception as exc:
        logger.error("[mention_pipeline] pipeline failed: %s", exc, exc_info=True)
        return {}
