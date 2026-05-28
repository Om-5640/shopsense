"""
Pipeline runner — bridges the CLI research pipeline to SSE events.

Each search gets a PipelineSession that runs in a daemon thread.
Events are pushed onto a Queue; the FastAPI SSE endpoint drains it.

The pipeline itself (research + scoring) is pure background work — no
interactive input() calls. Category detection, interview, and region
selection are handled by separate REST endpoints BEFORE this runs.
"""

import re as _re
import sys
import hashlib
import json
import logging
import threading
import queue
import time
import datetime
from pathlib import Path
from typing import Optional, Callable

_logger = logging.getLogger(__name__)

# ── Token budget constants (Phase 7) ─────────────────────────────────────────
# chars ≈ tokens * 4; these are conservative budgets leaving headroom for output.
_TOKEN_BUDGET_CHARS = {
    "groq":       24_000,
    "cerebras":   24_000,
    "gemini":    800_000,
    "mistral":    96_000,
    "openrouter": 80_000,
}
_DEFAULT_BUDGET_CHARS = 24_000   # safest assumption when provider unknown


def _estimate_tokens(text: str) -> int:
    """Approximate token count (4 chars ≈ 1 token for English)."""
    return max(1, len(text) // 4)


def _emit_token_warning(
    session: "PipelineSession",
    label: str,
    text: str,
    budget_chars: int,
) -> str:
    """
    If `text` exceeds `budget_chars`, emit an SSE warning and trim to fit.
    Returns the (possibly trimmed) text.
    Phase 7: overflow warnings surfaced in the SSE stream so UI can show them.
    """
    if len(text) > budget_chars:
        token_est = _estimate_tokens(text)
        budget_tok = budget_chars // 4
        session.emit_log(
            f"[token_budget] {label}: ~{token_est:,} tokens exceeds limit ~{budget_tok:,}. "
            f"Trimming to fit."
        )
        text = text[:budget_chars]
    return text

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
        self.status = "pending"   # pending | running | done | error | cancelled
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._created_at = time.time()
        self._cancelled = False
        # All events emitted so far — lets reconnected clients catch up
        self._event_log: list[dict] = []
        # Phase 11: pipeline diagnostics — populated during execution
        self.stats: dict = {
            "stage_timings": {},
            "product_count": 0,
            "thread_count": 0,
            "dedup_removed": 0,
            "llm_calls_estimated": 0,
            "tokens_estimated": 0,
            "warnings": [],
        }

    def emit(self, event_type: str, data: dict) -> None:
        item = {"type": event_type, "data": data}
        self._event_log.append(item)
        self.events.put(item)

    def emit_log(self, message: str) -> None:
        self.emit("log", {"message": message})
        # Phase 11: capture token_budget warnings in stats for diagnostics
        if "[token_budget]" in message and "exceeds" in message:
            self.stats["warnings"].append(message)

    def finish(self) -> None:
        """Signal that the SSE stream is over."""
        self.events.put(None)

    def cancel(self) -> None:
        """Request cancellation. The pipeline thread checks this between stages."""
        self._cancelled = True
        self.status = "cancelled"
        self.finish()


def create_session(search_id: str, query: str) -> "PipelineSession":
    session = PipelineSession(search_id, query)
    with _sessions_lock:
        _sessions[search_id] = session
    return session


def get_session(search_id: str) -> Optional["PipelineSession"]:
    with _sessions_lock:
        return _sessions.get(search_id)


def cancel_session(search_id: str) -> bool:
    """Cancel a running session. Returns True if the session existed."""
    with _sessions_lock:
        session = _sessions.get(search_id)
    if session:
        session.cancel()
        return True
    return False


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

def _pipeline_cache_key(query: str, category: str, rubric: dict, profile: dict | None = None) -> str:
    """
    Deterministic cache key: hash of query + category + rubric weights + current-session interview.
    Uses interview Q&A (not merged preferences_summary) to prevent cross-category memory signals
    from invalidating the cache for an unrelated search.
    """
    weights = sorted(
        (c["name"], c["weight"])
        for c in rubric.get("weighted_criteria", [])
    )
    # Fingerprint only the current-session interview answers, not the merged memory summary
    interview = (profile or {}).get("interview", []) if profile else []
    session_fingerprint = json.dumps(
        [(qa.get("question", ""), qa.get("answer", "")) for qa in interview],
        sort_keys=True,
    )
    payload = f"{query.lower().strip()}|{category}|{json.dumps(weights, sort_keys=True)}|{session_fingerprint}"
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


# ── Retrieval enrichment helpers (B3 + B4) ───────────────────────────────────

_USAGE_PATTERNS: list[tuple[str, str]] = [
    ("gaming",       "gaming"),
    ("game",         "gaming"),
    ("gym",          "gym workouts"),
    ("workout",      "gym workouts"),
    ("commut",       "commuting"),
    ("travel",       "travel"),
    ("office",       "office use"),
    ("work from home", "remote work"),
    ("running",      "running"),
    ("study",        "studying"),
    ("music",        "music listening"),
    ("creative",     "creative work"),
    ("photo",        "photography"),
    ("video edit",   "video editing"),
]


def _build_retrieval_query(base_query: str, profile: dict) -> str:
    """
    Augment retrieval query with primary usage context extracted from preferences.
    Adds 1 usage term (e.g., "gaming", "commuting") when clearly stated in the profile.
    Never modifies the query if no strong signal is found.
    """
    if not isinstance(profile, dict):
        return base_query
    prefs = (profile.get("preferences_summary") or "").lower()
    if not prefs:
        return base_query
    for keyword, hint in _USAGE_PATTERNS:
        if keyword in prefs and hint.lower() not in base_query.lower():
            enriched = f"{base_query} {hint}"
            return enriched[:100]  # cap at 100 chars
    return base_query


def _build_analyzer_hint(profile: dict) -> str:
    """
    Build a compact preference hint for the main analyzer.
    Prefers structured intent (hard_constraints first) when available.
    Falls back to truncated text summary.
    Max ~500 chars so it doesn't overwhelm the analyzer prompt.
    """
    if not isinstance(profile, dict):
        return ""

    intent = profile.get("intent")
    if intent and isinstance(intent, dict):
        parts = []
        if intent.get("hard_constraints"):
            parts.append("MUST: " + "; ".join(intent["hard_constraints"][:3]))
        if intent.get("budget"):
            parts.append(f"Budget: {intent['budget']}")
        if intent.get("preferences"):
            parts.append("Wants: " + "; ".join(intent["preferences"][:4]))
        if intent.get("exclusions"):
            parts.append("Excludes: " + "; ".join(intent["exclusions"][:2]))
        if parts:
            return "\n".join(parts)[:500]

    # Fallback to text summary if no structured intent
    prefs = (profile.get("preferences_summary") or "").strip()
    return prefs[:400] if prefs else ""


def _build_score_based_explanation(product: dict) -> str:
    """
    Deterministic (no-LLM) explanation from top/bottom scores.
    Used for products outside the top-N LLM explanation window.
    """
    scores = product.get("scores", [])
    if not scores:
        return ""
    by_contribution = sorted(scores, key=lambda s: s.get("weighted_contribution", 0), reverse=True)
    top = by_contribution[0] if by_contribution else None
    weak = [s for s in by_contribution if s.get("score", 5) <= 4]

    parts = []
    if top and top.get("score", 0) >= 7:
        parts.append(f"Strong in {top['label'].lower()}")
    if weak:
        parts.append(f"lower {weak[-1]['label'].lower()}")
    return ". ".join(parts) + "." if parts else ""


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


def _dedup_threads(threads: list[dict]) -> list[dict]:
    """
    Remove near-duplicate Reddit threads by title word overlap.
    Two threads are considered duplicates if >60% of their title words overlap.
    Keeps the higher-scored thread in each duplicate pair.
    Runs before summarization to avoid wasting API budget on repeated content.
    """
    if len(threads) <= 1:
        return threads

    # Sort by score descending so we always keep the better-scoring thread
    ranked = sorted(threads, key=lambda t: t.get("score", 0), reverse=True)

    _stop_words = {"the", "a", "an", "for", "in", "is", "are", "best", "good", "vs",
                   "of", "to", "and", "or", "what", "how", "does", "which", "i", "my",
                   "this", "that", "with", "by", "on", "at", "from", "be", "was", "has"}

    seen_token_sets: list[set] = []
    unique: list[dict] = []

    for t in ranked:
        title = (t.get("title") or "").lower()
        tokens = {w for w in _re.findall(r"[a-z0-9]{3,}", title) if w not in _stop_words}
        if not tokens:
            unique.append(t)
            seen_token_sets.append(tokens)
            continue

        is_dup = False
        for seen in seen_token_sets:
            if not seen:
                continue
            overlap = len(tokens & seen) / max(len(tokens | seen), 1)
            if overlap > 0.60:
                is_dup = True
                break

        if not is_dup:
            unique.append(t)
            seen_token_sets.append(tokens)

    removed = len(threads) - len(unique)
    if removed > 0:
        _logger.info("[pipeline] dedup: removed %d near-duplicate threads (%d → %d)", removed, len(threads), len(unique))
    return unique


def _write_pipeline_log(search_id: str, query: str, stats: dict) -> None:
    """
    Phase 11: Write a structured JSON log entry for this pipeline run.
    Appended to logs/pipeline_YYYY-MM-DD.jsonl in the project root.
    Non-fatal: any failure is silently swallowed.
    """
    try:
        logs_dir = _ROOT / "logs"
        logs_dir.mkdir(exist_ok=True)
        today = datetime.date.today().isoformat()
        log_file = logs_dir / f"pipeline_{today}.jsonl"
        entry = {
            "search_id": search_id,
            "query": query,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **stats,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as _log_err:
        _logger.debug("[pipeline_log] write failed (non-fatal): %s", _log_err)


def _check_cancelled(session: "PipelineSession") -> None:
    if session._cancelled:
        raise RuntimeError("Research stopped by user.")


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
    _cache_key = _pipeline_cache_key(query, category, rubric, profile)
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
    enriched_query = _build_retrieval_query(query, profile)
    if enriched_query != query:
        session.emit_log(f"[retrieval] query enriched: '{query}' → '{enriched_query}'")
    reddit_threads = fetch_all_threads(enriched_query, limit=limit, profile=profile)
    _stage_timings["reddit_fetch"] = round(time.time() - _t0, 1)
    session.stats["thread_count"] = len(reddit_threads)
    session.stats["stage_timings"]["reddit_fetch"] = _stage_timings["reddit_fetch"]
    session.emit("stage_done", {
        "stage": "reddit_fetch",
        "count": len(reddit_threads),
        "elapsed_s": _stage_timings["reddit_fetch"],
    })
    _check_cancelled(session)

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
        _check_cancelled(session)

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

    # Dedup near-identical threads before summarization to avoid wasting API budget
    deduped_threads = _dedup_threads(reddit_threads)
    _dedup_removed = len(reddit_threads) - len(deduped_threads)
    session.stats["dedup_removed"] = _dedup_removed
    session.stats["llm_calls_estimated"] += len(deduped_threads)  # one call per thread summary
    if _dedup_removed > 0:
        session.emit_log(
            f"[dedup] removed {_dedup_removed} near-duplicate threads"
        )

    def _on_thread_done(done: int, total: int, subreddit: str) -> None:
        session.emit("progress", {
            "stage": "summarize",
            "current": done,
            "total": total,
            "detail": f"r/{subreddit}",
        })

    thread_summaries = summarize_threads_parallel(
        deduped_threads, query, progress_callback=_on_thread_done
    )
    _stage_timings["summarize"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["summarize"] = _stage_timings["summarize"]
    session.emit("stage_done", {
        "stage": "summarize",
        "count": len(thread_summaries),
        "elapsed_s": _stage_timings["summarize"],
    })
    _check_cancelled(session)

    # ---- Stage 4: Main analysis aggregation ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "analyze",
        "label": "Analyzing Research",
    })
    primary_noun = options.get("primary_noun", category.split("/")[-1].replace("-", " "))
    preference_hint = _build_analyzer_hint(profile)
    analysis = analyze_with_summaries(
        query, thread_summaries, review_pages,
        primary_noun=str(primary_noun),
        preference_hint=preference_hint,
    )
    products = analysis.get("products", [])
    materials = analysis.get("materials", [])
    _stage_timings["analyze"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["analyze"] = _stage_timings["analyze"]
    session.stats["llm_calls_estimated"] += 1  # one main_analyzer call

    # W-03: Log products whose names have no overlap with primary_noun (potential off-category)
    _noun_words = {w for w in _re.findall(r'[a-z]{4,}', (primary_noun or "").lower())
                   if w not in ('best', 'good', 'most', 'with', 'that', 'this', 'from')}
    if _noun_words and len(products) > 3:
        _off = [p["name"] for p in products if not any(w in p.get("name", "").lower() for w in _noun_words)]
        if _off and len(_off) < len(products):
            session.emit_log(f"[W03] {len(_off)} products may be off-category for '{primary_noun}': {_off[:3]}")
    session.emit("stage_done", {
        "stage": "analyze",
        "products_found": len(products),
        "materials_found": len(materials),
        "elapsed_s": _stage_timings["analyze"],
    })
    _check_cancelled(session)

    if not products:
        session.emit("error", {"message": "No specific products found in research."})
        return

    # ---- Stage 4.5: Gap-fill rubric weights from research signal ----
    sources = normalize_all(reddit_threads, review_pages)
    research_text = _build_research_text(analysis, sources)
    # Phase 4: pass intent-aware user context so gap-filler sees hard constraints + budget
    _user_ctx = _build_analyzer_hint(profile) if isinstance(profile, dict) else ""
    rubric = fill_criterion_gaps(rubric, category, profile, research_text, user_context=_user_ctx)

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

    user_intent = (profile or {}).get("intent") if isinstance(profile, dict) else None

    # Phase 7: emit token estimate + enforce budget on research_text before scoring
    _rt_tokens = _estimate_tokens(research_text)
    session.emit_log(f"[token_budget] research_text: ~{_rt_tokens:,} tokens entering scorer")
    # Per-product budget handled inside scorer; trim total only when extreme
    research_text = _emit_token_warning(
        session, "research_text_total",
        research_text,
        _TOKEN_BUDGET_CHARS.get("gemini", 800_000),  # use Gemini limit as the ceiling
    )

    scored = score_all_products(
        products, rubric, research_text,
        progress_callback=_on_product_scored,
        user_intent=user_intent,
    )
    _stage_timings["scoring"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["scoring"] = _stage_timings["scoring"]
    session.stats["product_count"] = len(scored)
    # Estimate: ceil(products / 3) batch calls + top-5 explanation calls
    import math as _math
    session.stats["llm_calls_estimated"] += _math.ceil(len(products) / 3) + min(5, len(products))
    session.stats["tokens_estimated"] = _estimate_tokens(research_text) * len(products) // 3
    session.emit("stage_done", {
        "stage": "scoring",
        "count": len(scored),
        "elapsed_s": _stage_timings["scoring"],
    })

    # ---- Stage 5.5: Write personalized explanations ----
    # Top 5: rich LLM explanations. Remaining: deterministic score-based fallback.
    session.emit("stage_start", {"stage": "explanations", "label": "Writing Explanations"})
    try:
        from agents import run_agent
        from prompt_builder import assemble_prompt as _assemble_prompt
        # Phase 4: use intent-aware context (structured intent > preferences_summary)
        user_ctx_text = _build_analyzer_hint(profile) if isinstance(profile, dict) else ""
        _LLM_EXPLANATION_LIMIT = 5

        # LLM explanations for top products
        for idx, product in enumerate(scored[:_LLM_EXPLANATION_LIMIT]):
            criteria_scores = "\n".join(
                f"- {s['label']}: {s['score']}/10 — {s['evidence']}"
                for s in product.get("scores", [])[:6]
            )
            # Phase 5: assembled prompt with dedup + budget
            expl_prompt = _assemble_prompt([
                ("task", (
                    f"Category: {category}\n"
                    f"Product: {product['name']}\n"
                    f"Score: {product.get('percentage', 0):.0f}%\n"
                    f"Criterion scores:\n{criteria_scores}\n\n"
                    "Write 2-3 sentences explaining WHY this product fits this specific user's "
                    "stated preferences. Be personal and concrete. Start with the strongest reason."
                )),
                ("user_context", f"User preferences:\n{user_ctx_text or '(none given)'}"),
            ])
            try:
                expl = run_agent("explanation_writer", user_prompt=expl_prompt)
                scored[idx]["explanation"] = expl.strip()
            except Exception as e_err:
                session.emit_log(f"[explanation] product {idx} failed: {e_err}")
                scored[idx]["explanation"] = _build_score_based_explanation(product)

        # Score-based fallback for remaining products
        for idx in range(_LLM_EXPLANATION_LIMIT, len(scored)):
            if not scored[idx].get("explanation"):
                scored[idx]["explanation"] = _build_score_based_explanation(scored[idx])

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

    # Phase 7 + 11: Log total pipeline time with full diagnostics
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

    # Phase 11: Finalize stats and emit with done event
    session.stats["total_elapsed_s"] = _total_elapsed
    session.stats["stage_timings"]["total"] = _total_elapsed
    _logger.info(
        "[pipeline] diagnostics: %d threads, %d products, ~%d LLM calls, ~%d tokens",
        session.stats["thread_count"],
        session.stats["product_count"],
        session.stats["llm_calls_estimated"],
        session.stats["tokens_estimated"],
    )
    _write_pipeline_log(session.search_id, session.query, session.stats)
    session.emit("done", {
        "search_id": session.search_id,
        "elapsed_s": _total_elapsed,
        "diagnostics": session.stats,
    })
