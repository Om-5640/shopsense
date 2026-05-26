"""
Pipeline runner — bridges the CLI research pipeline to SSE events.

Each search gets a PipelineSession that runs in a daemon thread.
Events are pushed onto a Queue; the FastAPI SSE endpoint drains it.

The pipeline itself (research + scoring) is pure background work — no
interactive input() calls. Category detection, interview, and region
selection are handled by separate REST endpoints BEFORE this runs.
"""

import sys
import hashlib
import json
import logging
import threading
import queue
import time
from pathlib import Path
from typing import Optional, Callable

_logger = logging.getLogger(__name__)

# Ensure the project root is importable from within api/
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# In-memory session registry (survives only while the server is up)
_sessions: dict[str, "PipelineSession"] = {}
_sessions_lock = threading.Lock()


class PipelineSession:
    def __init__(self, search_id: str, query: str):
        self.search_id = search_id
        self.query = query
        self.events: queue.Queue = queue.Queue()
        self.status = "pending"   # pending | running | done | error
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._created_at = time.time()

    def emit(self, event_type: str, data: dict) -> None:
        self.events.put({"type": event_type, "data": data})

    def emit_log(self, message: str) -> None:
        self.emit("log", {"message": message})

    def finish(self) -> None:
        """Signal that the SSE stream is over."""
        self.events.put(None)


def create_session(search_id: str, query: str) -> "PipelineSession":
    session = PipelineSession(search_id, query)
    with _sessions_lock:
        _sessions[search_id] = session
    return session


def get_session(search_id: str) -> Optional["PipelineSession"]:
    with _sessions_lock:
        return _sessions.get(search_id)


def cleanup_old_sessions(max_age_hours: int = 6) -> int:
    """Remove done/error sessions older than max_age_hours, and hung running sessions older than 2×."""
    cutoff = time.time() - max_age_hours * 3600
    running_cutoff = time.time() - max_age_hours * 2 * 3600
    removed = 0
    with _sessions_lock:
        to_remove = [
            sid for sid, s in _sessions.items()
            if (s.status in ("done", "error") and s._created_at < cutoff)
            or (s.status == "running" and s._created_at < running_cutoff)
        ]
        for sid in to_remove:
            del _sessions[sid]
            removed += 1
    return removed


def start_pipeline(
    session: "PipelineSession",
    category: str,
    region: str,
    profile: dict,
    rubric: dict,
    options: dict,
) -> None:
    """Launch the research + scoring pipeline in a daemon thread."""

    def run() -> None:
        try:
            session.status = "running"
            _execute_pipeline(session, category, region, profile, rubric, options)
            session.status = "done"
        except Exception as exc:
            session.status = "error"
            session.error = str(exc)
            session.emit("error", {"message": str(exc)})
        finally:
            session.finish()

    t = threading.Thread(target=run, daemon=True, name=f"pipeline-{session.search_id}")
    t.start()


# ---------------------------------------------------------------------------
# Core pipeline execution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pipeline result cache (Phase 8) — skip full re-run for repeated searches
# ---------------------------------------------------------------------------

_PIPELINE_CACHE_TTL = 3600  # 1 hour

def _pipeline_cache_key(query: str, category: str, rubric: dict) -> str:
    """Deterministic cache key: hash of query + category + rubric weights."""
    weights = sorted(
        (c["name"], c["weight"])
        for c in rubric.get("weighted_criteria", [])
    )
    payload = f"{query.lower().strip()}|{category}|{json.dumps(weights, sort_keys=True)}"
    return hashlib.md5(payload.encode()).hexdigest()


def _load_pipeline_cache(key: str) -> Optional[dict]:
    try:
        import cache as _cache
        entry = _cache.get("pipeline_result", key)
        if entry and isinstance(entry, dict):
            if time.time() - entry.get("_cached_at", 0) < _PIPELINE_CACHE_TTL:
                return entry
    except Exception:
        pass
    return None


def _save_pipeline_cache(key: str, result: dict) -> None:
    try:
        import cache as _cache
        to_store = dict(result)
        to_store["_cached_at"] = time.time()
        _cache.set("pipeline_result", key, to_store)
    except Exception:
        pass


def _build_research_text(analysis: dict, sources: list) -> str:
    """Reconstruct the full research context for the scorer (mirrors run.py)."""
    parts = [f"=== COMMUNITY CONSENSUS ===\n{analysis.get('summary', '')}\n"]
    parts.append("\n=== PRODUCT EXTRACTS ===")
    for p in analysis.get("products", []):
        parts.append(f"\n{p['name']}")
        if p.get("praise"):
            parts.append(f"  Praise: {', '.join(p['praise'][:3])}")
        if p.get("complaints"):
            comps = [
                f"{c.get('text', '')} [{c.get('confidence', '?')}]"
                for c in p["complaints"][:3]
            ]
            parts.append(f"  Complaints: {'; '.join(comps)}")
        if p.get("representative_quote"):
            parts.append(f'  Quote: "{p["representative_quote"]}"')

    parts.append("\n\n=== RAW SOURCES (Reddit threads + review excerpts) ===")
    for s in sources:
        parts.append(f"\n--- {s['source_type'].upper()}: {s['source_name']} ---")
        parts.append(f"Title: {s.get('title', '')}")
        if s.get("body"):
            parts.append(f"Body: {s['body'][:2000]}")
        if s.get("discussions"):
            parts.append("Comments:")
            for d in s["discussions"][:20]:
                parts.append(f"  - {d['text'][:600]}")
    return "\n".join(parts)


def _execute_pipeline(
    session: "PipelineSession",
    category: str,
    region: str,
    profile: dict,
    rubric: dict,
    options: dict,
) -> None:
    """
    Runs all research stages and emits SSE events as it goes.
    This function runs in a background thread.
    """
    # Lazy imports — avoid loading heavy modules at server startup
    from reddit_fetch import fetch_all_threads, set_session_region
    from review_fetch import fetch_all_reviews
    from thread_summarizer import summarize_threads_parallel
    from llm_client import analyze_with_summaries
    from normalizer import normalize_all
    from rubric import fill_criterion_gaps
    from scorer import score_all_products

    query = session.query
    limit = options.get("limit", 15)
    no_reviews = options.get("no_reviews", False)
    _pipeline_start = time.time()
    _stage_timings: dict[str, float] = {}

    # ---- Phase 8: Pipeline cache check ----
    _cache_key = _pipeline_cache_key(query, category, rubric)
    _cached_result = _load_pipeline_cache(_cache_key)
    if _cached_result:
        age_s = int(time.time() - _cached_result.get("_cached_at", 0))
        session.emit("log", {"message": f"[cache] Returning cached result from {age_s}s ago"})
        session.emit("stage_start", {"stage": "cache_hit", "label": "Loading from Cache"})
        session.result = {k: v for k, v in _cached_result.items() if not k.startswith("_")}
        session.emit("stage_done", {"stage": "cache_hit", "elapsed_s": 0.1})
        session.emit("done", {"search_id": session.search_id, "from_cache": True})
        try:
            from db import update_search
            update_search(session.search_id, status="done", **session.result)
        except Exception:
            pass
        return

    # Set region for thread-local calls downstream
    set_session_region(region)

    # ---- Stage 1: Reddit fetch ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "reddit_fetch",
        "label": "Researching Reddit",
        "total": limit,
    })
    reddit_threads = fetch_all_threads(query, limit=limit)
    _stage_timings["reddit_fetch"] = round(time.time() - _t0, 1)
    session.emit("stage_done", {
        "stage": "reddit_fetch",
        "count": len(reddit_threads),
        "elapsed_s": _stage_timings["reddit_fetch"],
    })

    # ---- Stage 2: Review fetch ----
    review_pages: list = []
    if not no_reviews:
        _t0 = time.time()
        session.emit("stage_start", {
            "stage": "review_fetch",
            "label": "Scraping Expert Reviews",
        })
        review_pages = fetch_all_reviews(query, limit=options.get("reviews", 8))
        _stage_timings["review_fetch"] = round(time.time() - _t0, 1)
        session.emit("stage_done", {
            "stage": "review_fetch",
            "count": len(review_pages),
            "elapsed_s": _stage_timings["review_fetch"],
        })

    if not reddit_threads and not review_pages:
        session.emit("error", {"message": "No sources fetched. Try a different query."})
        return

    # ---- Stage 3: Parallel thread summarization ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "summarize",
        "label": "Summarizing Threads",
        "total": len(reddit_threads),
    })

    def _on_thread_done(done: int, total: int, subreddit: str) -> None:
        session.emit("progress", {
            "stage": "summarize",
            "current": done,
            "total": total,
            "detail": f"r/{subreddit}",
        })

    thread_summaries = summarize_threads_parallel(
        reddit_threads, query, progress_callback=_on_thread_done
    )
    _stage_timings["summarize"] = round(time.time() - _t0, 1)
    session.emit("stage_done", {
        "stage": "summarize",
        "count": len(thread_summaries),
        "elapsed_s": _stage_timings["summarize"],
    })

    # ---- Stage 4: Main analysis aggregation ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "analyze",
        "label": "Analyzing Research",
    })
    primary_noun = options.get("primary_noun", category.split("/")[-1].replace("-", " "))
    analysis = analyze_with_summaries(query, thread_summaries, review_pages,
                                      primary_noun=str(primary_noun))
    products = analysis.get("products", [])
    materials = analysis.get("materials", [])
    _stage_timings["analyze"] = round(time.time() - _t0, 1)
    session.emit("stage_done", {
        "stage": "analyze",
        "products_found": len(products),
        "materials_found": len(materials),
        "elapsed_s": _stage_timings["analyze"],
    })

    if not products:
        session.emit("error", {"message": "No specific products found in research."})
        return

    # ---- Stage 4.5: Gap-fill rubric weights from research signal ----
    sources = normalize_all(reddit_threads, review_pages)
    research_text = _build_research_text(analysis, sources)
    rubric = fill_criterion_gaps(rubric, category, profile, research_text)

    # ---- Stage 4.6: Cross-subreddit validation ----
    session.emit("stage_start", {
        "stage": "cross_validate",
        "label": "Cross-validating Sources",
    })
    try:
        from cross_validate import annotate_cross_subreddit
        analysis = annotate_cross_subreddit(analysis, thread_summaries, reddit_threads)
        # Refresh products list with cross_subreddit_signal field
        products = analysis.get("products", [])
    except Exception as cv_err:
        session.emit_log(f"[cross_validate] non-fatal: {cv_err}")
    session.emit("stage_done", {"stage": "cross_validate"})

    # ---- Stage 4.7: Precise mention counting + per-comment sentiment ----
    session.emit("stage_start", {
        "stage": "mention_counting",
        "label": "Counting Mentions (Precise)",
    })
    try:
        from mention_pipeline import run_pipeline as run_mention_pipeline
        from agents import run_agent as _agent_caller
        from alias_resolver import ProductInfo as _ProductInfo

        # Seed the registry with analysis-discovered products so the mention
        # counter always tries to find them — even if coref returns {} (which
        # happens when Reddit thread titles are vague / brand-free).
        _base_registry = {}
        for ap in products:
            _pname = ap.get("name", "").strip()
            if _pname:
                _base_registry[_pname.lower()] = _ProductInfo(canonical_name=_pname)

        mention_results = run_mention_pipeline(
            threads=reddit_threads,
            llm_client=_agent_caller,
            base_registry=_base_registry,
            run_sentiment=True,
        )

        # Build a lowercase lookup so case-drift between the LLM coref output
        # ("Realme Buds Air 7") and the analyser product name never causes a miss.
        mention_lower = {k.lower(): v for k, v in mention_results.items()}

        overwritten = 0
        for product in products:
            pname_lower = product.get("name", "").lower().strip()

            # Try exact case-insensitive match first
            mr = mention_lower.get(pname_lower)

            if mr:
                product["mention_count"] = mr.total_mentions
                product["distinct_recommenders"] = mr.distinct_threads
                product["positive_mentions"] = mr.positive
                product["negative_mentions"] = mr.negative
                # New fields — additive alongside existing ones
                product["sentiment_score"] = round(mr.sentiment_score, 3)
                product["dominant_sentiment"] = mr.dominant_sentiment
                product["sentiment_records"] = mr.sentiment_records[:20]
                overwritten += 1

        session.emit_log(
            f"[mention_pipeline] precise counts applied to {overwritten}/{len(products)} products"
        )
    except Exception as mp_err:
        session.emit_log(f"[mention_pipeline] non-fatal: {mp_err}")
        # Products keep their LLM-estimated counts — pipeline continues unaffected
    session.emit("stage_done", {"stage": "mention_counting"})

    # ---- Stage 5: Per-product scoring ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "scoring",
        "label": "Scoring Products",
        "total": len(products),
    })

    def _on_product_scored(current: int, total: int, name: str) -> None:
        session.emit("progress", {
            "stage": "scoring",
            "current": current,
            "total": total,
            "detail": name,
        })

    scored = score_all_products(
        products, rubric, research_text, progress_callback=_on_product_scored
    )
    _stage_timings["scoring"] = round(time.time() - _t0, 1)
    session.emit("stage_done", {
        "stage": "scoring",
        "count": len(scored),
        "elapsed_s": _stage_timings["scoring"],
    })

    # ---- Stage 5.5: Write "why this fits you" explanations for top 3 ----
    session.emit("stage_start", {"stage": "explanations", "label": "Writing Explanations"})
    try:
        from agents import run_agent
        profile_summary = profile.get("preferences_summary", "") if isinstance(profile, dict) else ""
        for idx, product in enumerate(scored[:3]):
            criteria_scores = "\n".join(
                f"- {s['label']}: {s['score']}/10 — {s['evidence']}"
                for s in product.get("scores", [])[:6]
            )
            expl_prompt = (
                f"Category: {category}\n"
                f"User's preferences: {profile_summary or '(none given)'}\n\n"
                f"Product: {product['name']}\n"
                f"Score: {product.get('percentage', 0):.0f}%\n"
                f"Criterion scores:\n{criteria_scores}\n\n"
                f"Write 2-3 sentences explaining WHY this product fits this specific user's stated "
                f"preferences. Be personal and concrete. Start with the strongest reason."
            )
            try:
                expl = run_agent("explanation_writer", user_prompt=expl_prompt)
                scored[idx]["explanation"] = expl.strip()
            except Exception as e_err:
                session.emit_log(f"[explanation] product {idx} failed: {e_err}")
    except Exception as expl_err:
        session.emit_log(f"[explanations] stage non-fatal: {expl_err}")
    session.emit("stage_done", {"stage": "explanations"})

    # ---- Stage 5.6: Apply product memory flags ----
    try:
        from memory import apply_product_memory_flags
        scored = apply_product_memory_flags(scored)
    except Exception as mem_err:
        session.emit_log(f"[memory] flags non-fatal: {mem_err}")

    # ---- Stage 6: Extract + persist user signals from interview Q&A ----
    try:
        from memory import extract_and_save_signals
        qa_history = options.get("qa_history", [])
        if qa_history:
            extract_and_save_signals(category, qa_history, source_search_id=session.search_id)
    except Exception as sig_err:
        session.emit_log(f"[memory] signal extraction non-fatal: {sig_err}")

    # ---- Persist result ----
    session.result = {
        "query": query,
        "category": category,
        "region": region,
        "profile": profile,
        "rubric": rubric,
        "analysis": analysis,
        "scoredProducts": scored,
    }

    # Phase 8: Save pipeline result to cache
    _save_pipeline_cache(_cache_key, session.result)

    # Phase 7: Log total pipeline time
    _total_elapsed = round(time.time() - _pipeline_start, 1)
    _timing_summary = ", ".join(f"{k}={v}s" for k, v in _stage_timings.items())
    _logger.info("[pipeline] TOTAL %ss | %s", _total_elapsed, _timing_summary)
    session.emit_log(f"Pipeline complete in {_total_elapsed}s")

    # Persist to DB
    try:
        from db import update_search
        update_search(
            session.search_id,
            status="done",
            category=category,
            region=region,
            profile=profile,
            rubric=rubric,
            analysis=analysis,
            scoredProducts=scored,
        )
    except Exception as db_err:
        session.emit_log(f"[db] write failed (non-fatal): {db_err}")

    session.emit("done", {"search_id": session.search_id, "elapsed_s": _total_elapsed})
