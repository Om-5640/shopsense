"""
Pipeline runner — bridges the CLI research pipeline to SSE events.

Each search gets a PipelineSession that runs in a daemon thread.
Events are pushed onto a Queue; the FastAPI SSE endpoint drains it.

The pipeline itself (research + scoring) is pure background work — no
interactive input() calls. Category detection, interview, and region
selection are handled by separate REST endpoints BEFORE this runs.
"""

import math as _math
import re as _re
import os
import sys
import hashlib
import json
import logging
import threading
import queue
import time
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

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


def _estimate_tokens(text: str) -> int:
    """Approximate token count (4 chars ≈ 1 token for English)."""
    return max(1, len(text) // 4)


# Must stay in sync with TOKEN_BUDGET_WARNING_PREFIX in web/lib/sse.ts
_TOKEN_BUDGET_PREFIX = "[token_budget]"


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
            f"{_TOKEN_BUDGET_PREFIX} {label}: ~{token_est:,} tokens exceeds limit ~{budget_tok:,}. "
            f"Trimming to fit."
        )
        text = text[:budget_chars]
    return text

# Ensure the project root is importable from within api/
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import reset_dead_providers as _reset_dead_providers


# In-memory session registry (survives only while the server is up)
# Hard cap: reject new sessions when this many are active, preventing unbounded memory growth.
# True horizontal scaling requires a shared session store (Redis), but a cap prevents OOM crashes.
_MAX_CONCURRENT_SESSIONS = 100
_sessions: dict[str, "PipelineSession"] = {}
_sessions_lock = threading.Lock()

_log_lock = threading.Lock()  # serialises concurrent append-writes to the daily pipeline log

_MAX_EVENT_LOG = 100  # cap per-session event replay log — 100 entries covers any reconnect scenario


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
        # Bounded event replay log — capped at _MAX_EVENT_LOG entries to prevent OOM
        self._event_log: list[dict] = []
        # Phase 11: pipeline diagnostics — populated during execution
        self.stats: dict = {
            "stage_timings": {},
            "product_count": 0,
            "thread_count": 0,
            "dedup_removed": 0,
            "llm_calls_estimated": 0,
            "tokens_estimated": 0,
            "warnings": [],           # token-budget truncation warnings
            "pipeline_warnings": [],  # provider fallback / infrastructure warnings
        }

    def emit(self, event_type: str, data: dict) -> None:
        item = {"type": event_type, "data": data}
        if event_type != "heartbeat" and len(self._event_log) < _MAX_EVENT_LOG:
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


def find_inflight_session(query: str) -> Optional["PipelineSession"]:
    """Return an existing running session for the same query, or None."""
    with _sessions_lock:
        for s in _sessions.values():
            if s.status == "running" and s.query == query:
                return s
    return None


def create_session(search_id: str, query: str) -> "PipelineSession":
    session = PipelineSession(search_id, query)
    with _sessions_lock:
        # Enforce session cap — evict oldest finished sessions first, then reject if still over cap
        if len(_sessions) >= _MAX_CONCURRENT_SESSIONS:
            _done = sorted(
                [(sid, s) for sid, s in _sessions.items() if s.status in ("done", "error", "cancelled")],
                key=lambda x: x[1]._created_at,
            )
            for sid, _ in _done[:max(1, len(_done) // 2)]:
                del _sessions[sid]
        if len(_sessions) >= _MAX_CONCURRENT_SESSIONS:
            raise RuntimeError(
                f"Server at capacity ({_MAX_CONCURRENT_SESSIONS} concurrent sessions). "
                "Please try again in a moment."
            )
        _sessions[search_id] = session
    # Reset provider dead-state so each new search gets a clean fallback chain.
    # The module-level _dead_providers set was persisting across requests, causing
    # providers exhausted in search N to be skipped permanently in searches N+1..∞.
    try:
        _reset_dead_providers()
    except Exception:
        pass
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


def cleanup_old_sessions(max_age_hours: int = 2) -> int:
    """Remove finished sessions after max_age_hours, cancelled sessions after 30 min, hung running after 4h."""
    cutoff = time.time() - max_age_hours * 3600
    cancelled_cutoff = time.time() - 1800   # 30 min — cancelled sessions hold no useful state
    running_cutoff = time.time() - 4 * 3600
    removed = 0
    with _sessions_lock:
        to_remove = [
            sid for sid, s in _sessions.items()
            if (s.status in ("done", "error") and s._created_at < cutoff)
            or (s.status == "cancelled" and s._created_at < cancelled_cutoff)
            or (s.status == "running" and s._created_at < running_cutoff)
        ]
        for sid in to_remove:
            del _sessions[sid]
            removed += 1
    return removed


def _run_heartbeat(session: "PipelineSession", stop_event: threading.Event, interval: int = 25) -> None:
    """Emit periodic heartbeat events so SSE clients don't time out during long stages."""
    while not stop_event.wait(interval):
        if session.status == "running":
            session.emit("heartbeat", {"ts": time.time()})


def start_pipeline(
    session: "PipelineSession",
    category: str,
    region: str,
    profile: dict,
    rubric: dict,
    options: dict,
) -> None:
    """Launch the research + scoring pipeline in a daemon thread."""
    _hb_stop = threading.Event()

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
            _hb_stop.set()
            session.finish()
            # Release the thread-local SQLite connection so this daemon thread
            # doesn't hold a file handle after the pipeline finishes (Bug M-3).
            try:
                from db import close_db_connection
                close_db_connection()
            except Exception:
                pass

    t = threading.Thread(target=run, daemon=True, name=f"pipeline-{session.search_id}")
    t.start()
    hb = threading.Thread(
        target=_run_heartbeat, args=(session, _hb_stop), daemon=True,
        name=f"heartbeat-{session.search_id}",
    )
    hb.start()


# ---------------------------------------------------------------------------
# Core pipeline execution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Pipeline result cache (Phase 8) — skip full re-run for repeated searches
# ---------------------------------------------------------------------------

_PIPELINE_CACHE_TTL = 86400  # 24 hours — product landscapes don't change hourly

def _pipeline_cache_key(query: str, category: str, rubric: dict, profile: dict | None = None) -> str:
    """
    Deterministic cache key: hash of query + category + rubric weights + interview Q&A.

    IMPORTANT: always call this AFTER fill_criterion_gaps() so the key reflects the
    gap-filled rubric weights. Calling it on the pre-gap rubric causes different users
    with identical pre-gap rubrics but different gap-fill results to share a stale cache entry.

    Includes interview Q&A (question+answer pairs) so two users with different stated needs
    but coincidentally identical gap-filled weights still get separate cache entries.
    Excludes preferences_summary: it is a merged/augmented view that changes with cross-search
    memory signals, which must not bust the cache for an otherwise identical search.
    """
    weights = sorted(
        (c["name"], c["weight"])
        for c in rubric.get("weighted_criteria", [])
    )
    qa_pairs: list[tuple[str, str]] = []
    if profile and isinstance(profile, dict):
        for qa in profile.get("interview", []):
            if isinstance(qa, dict):
                q = str(qa.get("question", "")).strip().lower()
                a = str(qa.get("answer", "")).strip().lower()
                if q or a:
                    qa_pairs.append((q, a))
        qa_pairs.sort()
    # Fix 4: Include a memory fingerprint so that adding or removing a preference
    # signal invalidates the cache for that user — preventing stale results that
    # predate the new preference. Guest users share cache entries (no per-user signals).
    memory_fp = ""
    user_id = (profile or {}).get("user_id", "default") if isinstance(profile, dict) else "default"
    if user_id and user_id not in ("default", "__legacy__"):
        try:
            from memory import list_user_signals as _list_signals
            _signals = _list_signals(user_id=user_id, limit=100)
            _sig_key = "|".join(sorted(
                f"{s.get('type', s.get('signal_type', ''))}"
                f"{s.get('text', s.get('signal_value', ''))}"
                f"{s.get('strength', '')}"
                for s in _signals
            ))
            memory_fp = "|mem:" + hashlib.md5(_sig_key.encode()).hexdigest()[:8]
        except Exception:
            pass

    payload = (
        f"{query.lower().strip()}|{category}"
        f"|{json.dumps(weights, sort_keys=True)}"
        f"|{json.dumps(qa_pairs)}"
        f"{memory_fp}"
    )
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
    # Tech / entertainment
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
    # Home / lifestyle
    ("kitchen",      "kitchen use"),
    ("cooking",      "cooking"),
    ("bedroom",      "bedroom"),
    ("living room",  "living room"),
    ("outdoor",      "outdoor use"),
    ("camping",      "camping"),
    ("hiking",       "hiking"),
    ("baby",         "baby use"),
    ("kids",         "kids"),
    ("pet",          "pet owner"),
    ("winter",       "winter use"),
    ("summer",       "summer use"),
    ("daily",        "everyday use"),
    # Beauty / personal care
    ("oily skin",    "oily skin"),
    ("dry skin",     "dry skin"),
    ("sensitive skin", "sensitive skin"),
    ("acne",         "acne-prone skin"),
    ("hair",         "hair care"),
    # Sports / fitness
    ("yoga",         "yoga"),
    ("cycling",      "cycling"),
    ("swim",         "swimming"),
    ("crossfit",     "crossfit"),
]


# Map criterion names to human-readable retrieval terms
_CRITERION_RETRIEVAL_HINTS: dict[str, str] = {
    "noise_cancellation": "noise cancellation",
    "battery_life": "battery life",
    "sound_quality": "sound quality",
    "call_quality": "call quality",
    "microphone_quality": "microphone",
    "water_resistance": "waterproof",
    "durability": "durability",
    "gaming_latency": "low latency gaming",
    "bass_response": "bass",
    "portability": "portable",
    "comfort": "comfort",
    "transparency_mode": "transparency mode",
    "price_to_value": "budget",
    "build_quality": "build quality",
    "connectivity": "multipoint bluetooth",
    "ecosystem_integration": "ecosystem",
}


def _build_retrieval_query(base_query: str, profile: dict, rubric: dict | None = None) -> str:
    """
    Augment retrieval query with:
    1. Primary usage context from profile preferences (e.g., "gaming", "commuting")
    2. Top-weighted rubric criterion terms so retrieval targets the user's actual priorities.

    Without criterion-aware enrichment, Reddit's most-popular threads dominate retrieval
    regardless of what the user actually cares about (RETRIEVAL-01 / CEILING-01 fix).
    """
    if not isinstance(profile, dict):
        return base_query

    # Step 1: usage-pattern enrichment (existing behaviour)
    prefs = (profile.get("preferences_summary") or "").lower()
    enriched = base_query
    if prefs:
        for keyword, hint in _USAGE_PATTERNS:
            if keyword in prefs and hint.lower() not in base_query.lower():
                enriched = f"{base_query} {hint}"
                break  # add at most one usage term

    # Step 2: inject top-weighted criterion term if not already covered
    if rubric and isinstance(rubric, dict):
        criteria = rubric.get("weighted_criteria", [])
        if criteria:
            # Find the highest-weight criterion that maps to a retrieval hint
            top_criteria = sorted(criteria, key=lambda c: c.get("weight", 0), reverse=True)
            for c in top_criteria[:3]:
                hint = _CRITERION_RETRIEVAL_HINTS.get(c.get("name", ""))
                if hint and hint.lower() not in enriched.lower():
                    enriched = f"{enriched} {hint}"
                    break  # add at most one criterion term

    # Steps 3 + 4: inject budget term and exclusion terms from structured intent
    _intent = profile.get("intent")
    if _intent and isinstance(_intent, dict):
        budget = _intent.get("budget", "")
        if budget and "budget" not in enriched.lower():
            enriched = f"{enriched} budget"
        for excl in _intent.get("exclusions", [])[:2]:
            excl_clean = excl.strip().lower()
            if excl_clean and excl_clean not in enriched.lower():
                enriched = f"{enriched} -{excl_clean}"

    # Word-boundary-safe truncation: cut at last space before limit
    limit = 120
    if len(enriched) > limit:
        cut = enriched[:limit].rsplit(" ", 1)[0]
        enriched = cut if cut else enriched[:limit]

    return enriched


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

    def _fmt_label(label: str) -> str:
        """Normalize snake_case or mixed-case criterion labels to human-readable title case."""
        return label.replace("_", " ").strip().lower()

    parts = []
    if top and top.get("score", 0) >= 7:
        parts.append(f"Strong in {_fmt_label(top['label'])}")
    if weak:
        parts.append(f"lower {_fmt_label(weak[-1]['label'])}")
    return ". ".join(parts) + "." if parts else ""


def _dedup_research_paragraphs(text: str) -> str:
    """
    Remove duplicate paragraphs from research text before scoring.
    Uses exact-match dedup on stripped paragraphs to eliminate repeated Reddit
    comment boilerplate (e.g. the same recommendation appearing in multiple threads).
    """
    if not text:
        return text
    paragraphs = _re.split(r"\n\s*\n", text)
    seen: set[str] = set()
    unique: list[str] = []
    for para in paragraphs:
        key = para.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(para)
    return "\n\n".join(unique)


def _build_research_text(analysis: dict, sources: list) -> str:
    """Reconstruct the full research context for the scorer (mirrors run.py)."""
    parts = [f"=== COMMUNITY CONSENSUS ===\n{analysis.get('summary', '')}\n"]
    parts.append("\n=== PRODUCT EXTRACTS ===")
    for p in analysis.get("products", []):
        parts.append(f"\n{p.get('name', '')}")
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
        parts.append(f"\n--- {s.get('source_type', 'source').upper()}: {s.get('source_name', '')} ---")
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
    Two threads are considered duplicates if >70% of their title words overlap.
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
            if overlap > 0.70:
                is_dup = True
                break

        if not is_dup:
            unique.append(t)
            seen_token_sets.append(tokens)

    removed = len(threads) - len(unique)
    if removed > 0:
        _logger.info("[pipeline] dedup: removed %d near-duplicate threads (%d → %d)", removed, len(threads), len(unique))
    return unique


def _build_review_intel_summary(review_pages: list[dict]) -> dict:
    """
    Extract review intelligence metadata from enriched review pages for the UI.
    Stored under analysis["review_intelligence"] so it flows through the existing
    JSON column with zero schema changes.  Non-fatal: returns empty structure on failure.
    """
    try:
        if not review_pages:
            return {"sources": [], "conflict_signals": [], "stats": {}}

        sources = []
        for page in review_pages:
            sr = page.get("structured_review") or {}
            is_trusted_channel = bool(page.get("channel_is_trusted"))
            explicit_tier = page.get("authority_tier")
            # YouTube trusted channels deserve "trusted" tier, not "good"
            if explicit_tier:
                authority_tier = explicit_tier
            elif is_trusted_channel:
                authority_tier = "trusted"
            else:
                authority_tier = "unknown"
            sources.append({
                "domain": page.get("domain", ""),
                "title": (page.get("title") or page.get("video_title") or "")[:120],
                "url": page.get("url", ""),
                "trust_score": round(float(page.get("domain_trust_score", page.get("trust_score", 0.5))), 3),
                "freshness_score": round(float(page.get("freshness_score", 0.5)), 3),
                "review_rank_score": round(float(page.get("review_rank_score", 0.5)), 3),
                "source_type": page.get("source_type", "gemini_grounding"),
                "authority_tier": authority_tier,
                "published_date": page.get("published_date"),
                "rating": sr.get("rating"),
                "verdict": (sr.get("verdict") or "")[:200] or None,
                # Structured content from expert reviews — surfaced in Sources tab
                "pros": (sr.get("pros") or [])[:5],
                "cons": (sr.get("cons") or [])[:5],
                "best_for": (sr.get("best_for") or [])[:3],
                "not_for": (sr.get("not_for") or [])[:3],
                # YouTube-specific: channel name for self-verification in the UI
                "channel_name": page.get("channel") or None,
            })

        conflict_signals = (review_pages[0].get("conflict_signals") or []) if review_pages else []
        total = len(sources)
        trusted = sum(1 for s in sources if s["authority_tier"] == "trusted")
        editorial = sum(1 for s in sources if s["source_type"] in ("gemini_grounding", "expert_editorial"))
        youtube = sum(1 for s in sources if s["source_type"] == "youtube")
        avg_trust = round(sum(s["trust_score"] for s in sources) / total, 3) if total else 0.0
        avg_freshness = round(sum(s["freshness_score"] for s in sources) / total, 3) if total else 0.0
        conflicts_found = sum(1 for c in conflict_signals if c.get("conflict"))

        return {
            "sources": sources,
            "conflict_signals": conflict_signals,
            "stats": {
                "total": total,
                "trusted_count": trusted,
                "editorial_count": editorial,
                "youtube_count": youtube,
                "avg_trust": avg_trust,
                "avg_freshness": avg_freshness,
                "conflicts_found": conflicts_found,
            },
        }
    except Exception as _e:
        _logger.debug("[review_intel] summary failed (non-fatal): %s", _e)
        return {"sources": [], "conflict_signals": [], "stats": {}}


def _write_pipeline_log(search_id: str, query: str, stats: dict) -> None:
    """
    Phase 11: Write a structured JSON log entry for this pipeline run.
    Appended to logs/pipeline_YYYY-MM-DD.jsonl in the project root.
    Non-fatal: any failure is silently swallowed.

    When LOG_FORMAT=json is set, also emits a single JSON line to stdout so
    log aggregators (Datadog, Loki, CloudWatch) can parse it natively.
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
        with _log_lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        # Structured stdout logging for production log aggregators
        if os.environ.get("LOG_FORMAT", "").lower() == "json":
            import sys
            print(json.dumps({
                "level": "info",
                "event": "pipeline_complete",
                "search_id": search_id,
                "query": query,
                "ts": entry["ts"],
                "thread_count": stats.get("thread_count", 0),
                "product_count": stats.get("product_count", 0),
                "llm_calls": stats.get("llm_calls_estimated", 0),
                "elapsed_s": stats.get("total_elapsed_s", 0),
                "scoring_mode": stats.get("scoring_mode", "unknown"),
                "provider_warnings": stats.get("pipeline_warnings", []),
                "token_warnings": len(stats.get("warnings", [])),
            }), file=sys.stdout, flush=True)
    except Exception as _log_err:
        _logger.debug("[pipeline_log] write failed (non-fatal): %s", _log_err)


def _check_cancelled(session: "PipelineSession") -> None:
    if session._cancelled:
        raise RuntimeError("Research stopped by user.")


def _collect_provider_warnings(initial_status: dict) -> list[str]:
    """
    Diff provider status at pipeline end vs start to produce human-readable
    warning strings surfaced in the UI as amber banners.

    Cases:
      - Provider was alive at start, dead at end     → quota / auth failure
      - Provider circuit breaker tripped during run  → repeated errors
      - All fast providers unavailable at start      → slower results expected
    """
    try:
        from agents import get_provider_status
        final = get_provider_status()
    except Exception:
        return []

    warnings: list[str] = []
    fast_providers = {"groq", "cerebras"}
    fast_configured = [p for p in fast_providers if initial_status.get(p, {}).get("configured")]
    fast_alive_start = [p for p in fast_configured if initial_status.get(p, {}).get("session_alive", True)]
    fast_alive_end   = [p for p in fast_configured if final.get(p, {}).get("session_alive", True)]

    for provider in ["groq", "cerebras", "mistral", "openrouter", "gemini"]:
        init = initial_status.get(provider, {})
        fin  = final.get(provider, {})
        if not init.get("configured"):
            continue

        was_alive = init.get("session_alive", True)
        is_alive  = fin.get("session_alive", True)
        circuit   = fin.get("circuit_blocked", False)
        was_circuit = init.get("circuit_blocked", False)

        if was_alive and not is_alive:
            label = provider.title()
            if provider == "groq":
                warnings.append(
                    f"Groq API quota was hit during this search — some calls used a fallback provider."
                )
            elif provider == "cerebras":
                warnings.append(
                    f"Cerebras became unavailable — fell back to a backup provider for summarization."
                )
            else:
                warnings.append(
                    f"{label} became unavailable during this search — a fallback provider was used."
                )

        if circuit and not was_circuit:
            warnings.append(
                f"{provider.title()} circuit breaker tripped (too many errors) — "
                f"excluded from remaining calls this session."
            )

    if fast_alive_start and not fast_alive_end:
        warnings.append(
            "All fast inference providers (Groq/Cerebras) became unavailable — "
            "this search ran on slower backup providers. Results are the same quality but took longer."
        )

    return warnings


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
    from thread_summarizer import summarize_threads_parallel, build_coref_maps_from_summaries
    from llm_client import analyze_with_summaries
    from normalizer import normalize_all
    from rubric import fill_criterion_gaps
    from scorer import score_all_products

    query = session.query
    limit = options.get("limit", 15)
    no_reviews = options.get("no_reviews", False)
    _pipeline_start = time.time()
    _stage_timings: dict[str, float] = {}
    # Computed once — profile doesn't change during a pipeline run
    _profile_hint = _build_analyzer_hint(profile) if isinstance(profile, dict) else ""

    # Snapshot provider status before any LLM calls so we can diff at the end
    # to produce human-readable pipeline_warnings for the UI.
    try:
        from agents import get_provider_status as _gps_initial
        _initial_provider_status = _gps_initial()
    except Exception:
        _initial_provider_status = {}

    # Set region for thread-local calls downstream (must happen before any reddit_fetch call)
    set_session_region(region)

    # ---- Phase 8: Pipeline cache check (uses pre-gap rubric key for fast hit) ----
    # We check cache here with the pre-gap rubric. After gap-filling we recompute the key
    # and save under the post-gap key. On subsequent runs the pre-gap lookup will miss
    # (weights differ) and we'll find the post-gap entry instead — ensuring no stale results.
    _pre_gap_cache_key = _pipeline_cache_key(query, category, rubric, profile)
    _cached_result = _load_pipeline_cache(_pre_gap_cache_key)

    # Semantic cache: if no exact hit, check whether a near-identical query (same category,
    # region, and rubric) was researched recently and reuse its result — skipping all research.
    try:
        import semantic_cache as _semcache
        _rubric_fp = _semcache.fingerprint(rubric)  # pre-gap fingerprint; registered the same way
    except Exception:
        _semcache = None
        _rubric_fp = None
    if not _cached_result and _semcache is not None:
        _sem_key = _semcache.lookup(query, category, region, _rubric_fp)
        if _sem_key:
            _sem_hit = _load_pipeline_cache(_sem_key)
            if _sem_hit:
                session.emit("log", {"message": "[cache] Semantic match — reusing a near-identical recent search"})
                _cached_result = _sem_hit

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
        # Still extract signals from interview even on cache hit — memory must always learn.
        try:
            from memory import extract_and_save_signals
            qa_history = options.get("qa_history", [])
            _uid = options.get("user_id", "default")
            if qa_history:
                extract_and_save_signals(
                    category, qa_history,
                    source_search_id=session.search_id,
                    user_id=_uid,
                )
        except Exception:
            pass
        return

    # ---- Stage 1: Reddit fetch ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "reddit_fetch",
        "label": "Researching Reddit",
        "total": limit,
    })
    enriched_query = _build_retrieval_query(query, profile, rubric=rubric)
    if enriched_query != query:
        session.emit_log(f"[retrieval] query enriched: '{query}' → '{enriched_query}'")
    reddit_threads = fetch_all_threads(
        enriched_query, limit=limit, profile=profile,
        cancel_fn=lambda: session._cancelled,
    )
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

    # Review intelligence summary — built once after fetch, embedded into analysis before save
    _review_intel = _build_review_intel_summary(review_pages)

    # ---- Stage 4: Main analysis aggregation ----
    _t0 = time.time()
    session.emit("stage_start", {
        "stage": "analyze",
        "label": "Analyzing Research",
    })
    primary_noun = options.get("primary_noun", category.split("/")[-1].replace("-", " "))
    analysis = analyze_with_summaries(
        query, thread_summaries, review_pages,
        primary_noun=str(primary_noun),
        preference_hint=_profile_hint,
    )
    products = analysis.get("products", [])
    _stage_timings["analyze"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["analyze"] = _stage_timings["analyze"]
    session.stats["llm_calls_estimated"] += 1  # one main_analyzer call

    # W-03: Detect and filter products that don't match primary_noun.
    # Fixes from audit:
    #   - Lower minimum word length to 2 so "AC", "TV", "PC" are not skipped.
    #   - Use word-boundary regex instead of substring containment to reduce false positives.
    #   - Actually filter (not just log) when confidence is high: <40% of products flagged,
    #     at least 3 survivors, and noun is specific enough (≥3 chars).
    _noun_lower = (primary_noun or "").strip().lower()
    _w03_stop = {'best', 'good', 'most', 'with', 'that', 'this', 'from', 'the', 'and', 'for'}
    _noun_words = {w for w in _re.findall(r'[a-z0-9]{2,}', _noun_lower) if w not in _w03_stop}
    _noun_pats = [_re.compile(r'\b' + _re.escape(w) + r'\b') for w in _noun_words]

    def _name_matches_noun(name: str) -> bool:
        nl = name.lower()
        return any(p.search(nl) for p in _noun_pats)

    if _noun_pats and len(products) > 3:
        _off = [p for p in products if not _name_matches_noun(p.get("name", ""))]
        if _off and len(_off) < len(products):
            session.emit_log(
                f"[W03] {len(_off)} products may be off-category for '{primary_noun}': "
                f"{[p.get('name', '?') for p in _off[:3]]}"
            )
            # Filter only when confident: <40% flagged, ≥3 survivors, noun specific enough
            _on = [p for p in products if _name_matches_noun(p.get("name", ""))]
            if len(_on) >= 3 and len(_off) / len(products) < 0.4 and len(_noun_lower) >= 3:
                products = _on
                session.emit_log(f"[W03] filtered to {len(products)} on-category products")
    session.emit("stage_done", {
        "stage": "analyze",
        "products_found": len(products),
        "elapsed_s": _stage_timings["analyze"],
    })
    _check_cancelled(session)

    if not products:
        session.emit("error", {"message": "No specific products found in research."})
        return

    # ---- Stage 4.5: Gap-fill rubric weights from research signal ----
    sources = normalize_all(reddit_threads, review_pages)
    research_text = _dedup_research_paragraphs(_build_research_text(analysis, sources))
    rubric = fill_criterion_gaps(rubric, category, profile, research_text, user_context=_profile_hint)

    # Post-gap cache check: if a prior run produced identical gap-filled weights, skip all
    # scoring stages (the most expensive part). Reddit/review/summarize/analyze already ran,
    # but scoring + explanations (~8+ LLM calls) are skipped.
    _post_gap_cache_key = _pipeline_cache_key(query, category, rubric, profile)
    if _post_gap_cache_key != _pre_gap_cache_key:
        _post_gap_cached = _load_pipeline_cache(_post_gap_cache_key)
        if _post_gap_cached:
            age_s = int(time.time() - _post_gap_cached.get("_cached_at", 0))
            session.emit_log(f"[cache] Post-gap hit from {age_s}s ago — skipping scoring")
            session.result = {k: v for k, v in _post_gap_cached.items() if not k.startswith("_")}
            try:
                from memory import extract_and_save_signals
                qa_history = options.get("qa_history", [])
                if qa_history:
                    extract_and_save_signals(
                        category, qa_history,
                        source_search_id=session.search_id,
                        user_id=options.get("user_id", "default"),
                    )
            except Exception:
                pass
            try:
                from db import update_search
                update_search(session.search_id, status="done", **session.result)
            except Exception:
                pass
            session.emit("done", {"search_id": session.search_id, "from_cache": True})
            return

    # ---- Stage 4.6: Cross-subreddit validation ----
    _t0 = time.time()
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
    _stage_timings["cross_validate"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["cross_validate"] = _stage_timings["cross_validate"]
    session.emit("stage_done", {"stage": "cross_validate", "elapsed_s": _stage_timings["cross_validate"]})
    _check_cancelled(session)

    # ---- Stage 4.7: Precise mention counting + per-comment sentiment ----
    _t0 = time.time()
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
            pre_coref_maps=build_coref_maps_from_summaries(thread_summaries),
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

    # Fix 1: Hallucination filter — drop products with zero text corroboration.
    # An LLM can confidently name a product that never appeared in any source.
    # Keep a product only if the Aho-Corasick automaton found ≥1 confirmed text hit
    # (mention_count > 0) OR the LLM attributed it to at least one source URL/subreddit.
    # Review-site-only products have no Reddit mention count but a valid sources list.
    _pre_hallucination = len(products)
    products = [
        p for p in products
        if p.get("mention_count", 0) > 0 or p.get("sources")
    ]
    _hallucination_dropped = _pre_hallucination - len(products)
    if _hallucination_dropped:
        session.emit_log(
            f"[hallucination_filter] removed {_hallucination_dropped} product(s) "
            f"with no text corroboration and no source attribution"
        )
        session.stats["hallucination_filter_dropped"] = _hallucination_dropped

    _stage_timings["mention_counting"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["mention_counting"] = _stage_timings["mention_counting"]
    session.emit("stage_done", {"stage": "mention_counting", "elapsed_s": _stage_timings["mention_counting"]})
    _check_cancelled(session)

    # Fix 2: Pre-scoring hard constraint filter — remove products that clearly violate
    # the user's MUST/MUST-NOT requirements before any LLM scoring call runs.
    # Violations are preserved in constraint_violations so the result can surface them.
    user_intent = (profile or {}).get("intent") if isinstance(profile, dict) else None
    constraint_violations: list[dict] = []
    if user_intent and (user_intent.get("hard_constraints") or user_intent.get("exclusions")):
        _t_cf = time.time()
        session.emit("stage_start", {"stage": "constraint_filter", "label": "Checking Requirements"})
        try:
            from scorer import filter_constraint_violators
            products, constraint_violations = filter_constraint_violators(
                products, user_intent, research_text
            )
            if constraint_violations:
                session.emit_log(
                    f"[constraint_filter] excluded {len(constraint_violations)} product(s) "
                    f"that violate hard user requirements"
                )
                session.stats["constraint_violations_excluded"] = len(constraint_violations)
        except Exception as _cf_err:
            session.emit_log(f"[constraint_filter] non-fatal: {_cf_err}")
        session.emit("stage_done", {
            "stage": "constraint_filter",
            "elapsed_s": round(time.time() - _t_cf, 1),
        })
        _check_cancelled(session)

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
        cancelled_check=lambda: session._cancelled,
    )
    _stage_timings["scoring"] = round(time.time() - _t0, 1)
    session.stats["stage_timings"]["scoring"] = _stage_timings["scoring"]
    session.stats["product_count"] = len(scored)
    session.stats["llm_calls_estimated"] += _math.ceil(len(products) / 3) + min(5, len(products))
    session.stats["tokens_estimated"] = _estimate_tokens(research_text) * len(products) // 3
    session.emit("stage_done", {
        "stage": "scoring",
        "count": len(scored),
        "elapsed_s": _stage_timings["scoring"],
    })

    # ---- Stage 5.4: Targeted evidence enrichment (fill high-impact data gaps) ----
    # For the top products' highest-weight criteria that came back with no research evidence,
    # fetch the real fact via a targeted web search instead of leaving it peer-mean imputed.
    # Fully wrapped + flag-gated — any failure leaves `scored` exactly as it was.
    try:
        from evidence_enricher import enrich_scores, ENABLE_TARGETED_FETCH
        if ENABLE_TARGETED_FETCH:
            session.emit("stage_start", {"stage": "enrichment", "label": "Filling data gaps"})
            _t_enrich = time.time()
            scored = enrich_scores(
                scored, rubric, region,
                cancelled_check=lambda: session._cancelled,
            )
            _stage_timings["enrichment"] = round(time.time() - _t_enrich, 1)
            session.emit("stage_done", {"stage": "enrichment", "elapsed_s": _stage_timings["enrichment"]})
    except Exception as _enrich_err:
        session.emit_log(f"[enrichment] stage non-fatal: {_enrich_err}")

    # ---- Stage 5.5: Write personalized explanations ----
    # Top 5: rich LLM explanations run in parallel. Remaining: deterministic score-based fallback.
    session.emit("stage_start", {"stage": "explanations", "label": "Writing Explanations"})
    try:
        from agents import run_agent
        from prompt_builder import assemble_prompt as _assemble_prompt

        _LLM_EXPLANATION_LIMIT = 5

        def _make_expl_prompt(product: dict) -> str:
            criteria_scores = "\n".join(
                f"- {s['label']}: {s['score']}/10 — {s['evidence']}"
                for s in product.get("scores", [])[:6]
            )
            # CEILING-03: ground the explanation in actual evidence strings to prevent hallucination
            return _assemble_prompt([
                ("task", (
                    f"Category: {category}\n"
                    f"Product: {product.get('name', '')}\n"
                    f"Score: {product.get('percentage', 0):.0f}%\n"
                    f"Criterion scores (with evidence from research):\n{criteria_scores}\n\n"
                    "Write 2-3 sentences explaining WHY this product fits this specific user's "
                    "stated preferences. Base your explanation ONLY on the evidence strings above — "
                    "do not invent claims not supported by that evidence. "
                    "Be personal and concrete. Start with the strongest reason."
                )),
                ("user_context", f"User preferences:\n{_profile_hint or '(none given)'}"),
            ], budget_chars=6000)

        def _fetch_explanation(args: tuple) -> tuple:
            idx, product = args
            try:
                return idx, run_agent("explanation_writer", user_prompt=_make_expl_prompt(product)).strip()
            except Exception:
                return idx, _build_score_based_explanation(product)

        top = list(enumerate(scored[:_LLM_EXPLANATION_LIMIT]))
        with ThreadPoolExecutor(max_workers=_LLM_EXPLANATION_LIMIT) as _pool:
            for idx, expl in _pool.map(_fetch_explanation, top):
                scored[idx]["explanation"] = expl or _build_score_based_explanation(scored[idx])

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
        _user_id = options.get("user_id", "default")
        if qa_history:
            extract_and_save_signals(
                category, qa_history,
                source_search_id=session.search_id,
                user_id=_user_id,
            )
    except Exception as sig_err:
        session.emit_log(f"[memory] signal extraction non-fatal: {sig_err}")

    # Embed review intelligence into analysis so it flows through the existing JSON column
    # without any DB schema changes.  Frontend reads it as data.analysis.review_intelligence.
    analysis["review_intelligence"] = _review_intel

    # ---- Persist result ----
    session.result = {
        "query": query,
        "category": category,
        "region": region,
        "profile": profile,
        "rubric": rubric,
        "analysis": analysis,
        "scoredProducts": scored,
        "constraintViolations": constraint_violations,
    }

    _save_pipeline_cache(_post_gap_cache_key, session.result)

    # Register this search in the semantic cache so future near-identical queries reuse it.
    # Uses the pre-gap rubric fingerprint to match the pre-research lookup above.
    if _semcache is not None and _rubric_fp is not None:
        _semcache.register(query, category, region, _rubric_fp, _post_gap_cache_key)

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
            constraintViolations=constraint_violations,
        )
    except Exception as db_err:
        session.emit_log(f"[db] write failed (non-fatal): {db_err}")

    # Phase 11: Finalize stats and emit with done event
    session.stats["total_elapsed_s"] = _total_elapsed
    session.stats["stage_timings"]["total"] = _total_elapsed

    # Add the fixed-count calls that weren't tracked inline:
    #   cross_validator: 1 call
    #   gap_filler: 1 call (skipped when <2 defaults, but count it)
    #   explanation_writer: min(5, product_count) calls
    #   signal_extractor: 1 call (if qa_history provided)
    #   sentiment (thread-level batch): up to len(deduped_threads) calls (now ≤15)
    session.stats["llm_calls_estimated"] += (
        1  # cross_validator
        + 1  # gap_filler
        + min(5, session.stats["product_count"])  # explanation_writer
        + 1  # signal_extractor
        + session.stats["thread_count"]  # sentiment: one batch call per thread max
    )

    # Enrich pipeline log with scoring mode and live provider status
    try:
        from scorer import SCORING_MODE as _scoring_mode
        session.stats["scoring_mode"] = _scoring_mode
    except Exception:
        session.stats["scoring_mode"] = "unknown"
    try:
        from agents import get_provider_status as _gps
        _pstatus = _gps()
        session.stats["providers_used"] = [
            p for p, info in _pstatus.items()
            if info.get("session_alive") and not info.get("circuit_blocked")
        ]
    except Exception:
        session.stats["providers_used"] = []

    # Collect provider fallback warnings by diffing initial vs final provider status
    _provider_warnings = _collect_provider_warnings(_initial_provider_status)
    if _provider_warnings:
        session.stats["pipeline_warnings"] = _provider_warnings
        for w in _provider_warnings:
            _logger.warning("[pipeline] provider warning: %s", w)

    _logger.info(
        "[pipeline] diagnostics: %d threads, %d products, ~%d LLM calls, ~%d tokens, mode=%s, "
        "%d provider warnings",
        session.stats["thread_count"],
        session.stats["product_count"],
        session.stats["llm_calls_estimated"],
        session.stats["tokens_estimated"],
        session.stats.get("scoring_mode", "?"),
        len(_provider_warnings),
    )
    _write_pipeline_log(session.search_id, session.query, session.stats)
    session.emit("done", {
        "search_id": session.search_id,
        "elapsed_s": _total_elapsed,
        "diagnostics": session.stats,
        "pipeline_warnings": session.stats["pipeline_warnings"],
    })
