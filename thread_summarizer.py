"""
Parallel thread summarization.

Instead of feeding all 15 raw Reddit threads (150K+ chars) into one massive
analyzer call, we spawn a dedicated sub-agent PER THREAD that produces a
small structured summary. The main analyzer then aggregates these summaries.

Why this is better:
- Smaller focused context = better extraction quality (less cognitive overload)
- Parallel = total wall time bounded by slowest thread, not sum of all
- Per-thread failures are isolated (1 bad thread doesn't ruin the run)
- Main analyzer sees clean structured data, not raw noisy comments

Concurrency: bounded to MAX_PARALLEL_WORKERS to avoid bursting Groq's rate limit.
"""

import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents import run_agent
from llm_client import _try_repair_json


# Adaptive parallelism: start at 5, throttle back to 3 on repeated 429s
MAX_PARALLEL_WORKERS = 5
_MIN_WORKERS = 2
# No baseline stagger needed: ThreadPoolExecutor bounds concurrency to MAX_PARALLEL_WORKERS,
# so we never burst all threads simultaneously regardless. Stagger only activates after a 429.
SUBMISSION_STAGGER_DELAY = 0.0

# Adaptive throttle state — shared across parallel workers
_throttle_lock = threading.Lock()
_throttle_until: float = 0.0          # epoch time when throttle lifts
_throttle_active: bool = False


def _set_throttled(duration_s: float = 30.0) -> None:
    """Signal that rate limits were hit — increase stagger for next submissions."""
    global _throttle_until, _throttle_active
    with _throttle_lock:
        _throttle_until = time.time() + duration_s
        _throttle_active = True


def _get_stagger() -> float:
    """Return stagger delay to use between submissions."""
    with _throttle_lock:
        if _throttle_active and time.time() < _throttle_until:
            return 2.5  # throttled: slow down
        return SUBMISSION_STAGGER_DELAY

# Max chars of thread content per summarizer call (fits Groq 8K token limit).
MAX_CHARS_PER_THREAD = 12000


SUMMARIZER_SYSTEM = """You are a focused summarizer. You read ONE Reddit thread and extract a structured summary.

Return ONLY a JSON object:
{
  "thread_summary": "1-2 sentence neutral summary of what's being discussed and overall sentiment",
  "products_mentioned": [
    {
      "name": "Brand Model Name (exact as mentioned)",
      "sentiment": "positive|negative|mixed",
      "mention_count": 0,
      "key_quotes": ["short quote 1", "short quote 2"]
    }
  ],
  "categories_mentioned": ["material/type", "..."],
  "key_takeaways": [
    "Most-upvoted insight in this thread",
    "Notable counter-opinion or complaint",
    "Unique recommendation only in this thread"
  ],
  "top_comments": [
    {"text": "verbatim short quote", "upvotes": 0}
  ],
  "total_upvotes": 0,
  "controversial_signals": ["specific complaint with high upvotes despite disagreement"],
  "aliases": {
    "Brand Model Name": ["shorthand1", "nickname", "informal reference seen in this thread"]
  }
}

RULES:
1. Only extract products with brand names (e.g. "Casio MDV-106"), not generic types ("a dive watch").
2. Categories ARE generic types ("dive watches", "quartz", "leather strap").
3. Quotes must be EXACT — never invent.
4. Cap products at 8, categories at 5, takeaways at 4, top_comments at 5.
5. Sentiment: "positive" if 2+ users praise it, "negative" if 2+ complain, "mixed" otherwise.
6. controversial_signals: only include if controversial-tagged comments expose real concerns.
7. If thread is off-topic or unhelpful, return mostly-empty fields with thread_summary explaining why.
8. aliases: for each product in products_mentioned, list every shorthand/nickname ACTUALLY seen in
   this thread (e.g. "XM5" for "Sony WF-1000XM5", "RBA7" for "Realme Buds Air 7"). Empty dict {} is
   fine if no nicknames appear. NEVER merge different products — "Air 7" and "Air 7 Pro" stay separate.

NO markdown, NO commentary. JSON only."""


def _build_thread_prompt(thread: dict, query: str) -> str:
    """Build the summarizer prompt for a single thread."""
    lines = [
        f"USER'S SHOPPING QUERY: {query}",
        "",
        "REDDIT THREAD",
        f"Subreddit: r/{thread.get('subreddit', '?')}",
        f"Title: {thread.get('title', '')}",
        f"Score: +{thread.get('score', 0)} | Total comments in thread: {thread.get('total_comment_count_in_thread', '?')}",
    ]

    body = (thread.get("body") or "").strip()
    if body:
        lines.append(f"Post body: {body[:1500]}")

    lines.append("")
    lines.append("COMMENTS (most upvoted first, indented = reply, [C] = controversial):")

    chars_used = sum(len(line) for line in lines)
    all_comments = thread.get("comments", [])
    comments_added = 0
    for c in all_comments:
        depth = c.get("depth", 0)
        indent = "  " * (depth + 1)
        tag = ""
        if depth > 0:
            tag += f"(reply L{depth}) "
        if c.get("from_controversial"):
            tag += "[C] "
        line = f"{indent}[+{c.get('score', 0)}] {tag}{c.get('body', '')}"
        if chars_used + len(line) > MAX_CHARS_PER_THREAD:
            remaining = len(all_comments) - comments_added
            lines.append(f"{indent}[... {remaining} more comments truncated for length]")
            break
        lines.append(line)
        chars_used += len(line)
        comments_added += 1

    lines.append("")
    lines.append("Summarize this thread into the JSON schema above.")
    return "\n".join(lines)


def _coerce_str(v) -> str:
    """Defensive: coerce any value to string."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:500]
    return str(v)


def _coerce_list(v) -> list:
    """Defensive: coerce any value to a list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, (str, dict)):
        return [v]
    return []


def _summarize_one_thread(thread: dict, query: str) -> dict:
    """
    Run the thread_summarizer agent on a single thread.
    Returns the parsed JSON summary, or a degraded fallback on failure.
    Output is defensively normalized to canonical shape - never crashes downstream.
    """
    url = thread.get("url", "?")
    subreddit = thread.get("subreddit", "?")

    try:
        prompt = _build_thread_prompt(thread, query)
        raw = run_agent("thread_summarizer", user_prompt=prompt, system=SUMMARIZER_SYSTEM)
        data = _try_repair_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "rate" in err_str or "circuit" in err_str:
            _set_throttled(30.0)
        return {
            "url": url,
            "subreddit": subreddit,
            "thread_summary": f"(summarization failed: {type(e).__name__})",
            "products_mentioned": [],
            "categories_mentioned": [],
            "key_takeaways": [],
            "top_comments": [],
            "total_upvotes": thread.get("score", 0),
            "controversial_signals": [],
            "_failed": True,
        }

    # Defensive normalization of every field
    normalized_products = []
    for p in _coerce_list(data.get("products_mentioned")):
        if isinstance(p, str):
            normalized_products.append({"name": p, "sentiment": "mixed", "mention_count": 1, "key_quotes": []})
        elif isinstance(p, dict) and p.get("name"):
            normalized_products.append({
                "name": _coerce_str(p.get("name")),
                "sentiment": _coerce_str(p.get("sentiment", "mixed")).lower() or "mixed",
                "mention_count": int(p.get("mention_count", 1)) if str(p.get("mention_count", 1)).replace("-", "").isdigit() else 1,
                "key_quotes": [_coerce_str(q) for q in _coerce_list(p.get("key_quotes"))[:5] if _coerce_str(q)],
            })

    normalized_comments = []
    for c in _coerce_list(data.get("top_comments")):
        if isinstance(c, str):
            normalized_comments.append({"text": c, "upvotes": 0})
        elif isinstance(c, dict):
            text = _coerce_str(c.get("text") or c.get("comment") or c.get("body"))
            if text:
                upvotes_raw = c.get("upvotes", 0)
                upvotes = int(upvotes_raw) if str(upvotes_raw).replace("-", "").isdigit() else 0
                normalized_comments.append({"text": text, "upvotes": upvotes})

    # Normalize aliases: {canonical_name: [alias, ...]} — mirrors coref_pass output format
    raw_aliases = data.get("aliases") or {}
    normalized_aliases: dict[str, list[str]] = {}
    if isinstance(raw_aliases, dict):
        for name, alias_list in raw_aliases.items():
            name_str = _coerce_str(name).strip()
            if not name_str:
                continue
            clean = [
                _coerce_str(a).strip()
                for a in _coerce_list(alias_list)
                if _coerce_str(a).strip() and _coerce_str(a).strip().lower() != name_str.lower()
            ]
            if clean:
                normalized_aliases[name_str] = clean

    # Build fully-normalized output (don't trust raw LLM structure)
    return {
        "url": url,
        "subreddit": subreddit,
        "thread_summary": _coerce_str(data.get("thread_summary", "")),
        "products_mentioned": normalized_products,
        "categories_mentioned": [_coerce_str(c) for c in _coerce_list(data.get("categories_mentioned")) if _coerce_str(c)],
        "key_takeaways": [_coerce_str(t) for t in _coerce_list(data.get("key_takeaways")) if _coerce_str(t)],
        "top_comments": normalized_comments,
        "total_upvotes": int(data.get("total_upvotes", thread.get("score", 0))) if str(data.get("total_upvotes", 0)).replace("-", "").isdigit() else thread.get("score", 0),
        "controversial_signals": [_coerce_str(c) for c in _coerce_list(data.get("controversial_signals")) if _coerce_str(c)],
        "thread_score": thread.get("score", 0),
        "total_comment_count": thread.get("total_comment_count_in_thread", 0),
        "aliases": normalized_aliases,
        "_failed": False,
    }


def summarize_threads_parallel(
    threads: list[dict],
    query: str,
    progress_callback=None,
) -> list[dict]:
    """
    Spawn a parallel pool of thread_summarizer agents, one per thread.
    Returns a list of summary dicts in the SAME ORDER as input threads.

    Bounded by MAX_PARALLEL_WORKERS to avoid hitting Groq's per-minute rate limit.
    Per-thread failures are isolated (the main analyzer still gets all successful ones).

    progress_callback(done: int, total: int, subreddit: str) — called after each thread
    completes. Used by the API layer to stream SSE progress events.
    """
    if not threads:
        return []

    # Adaptive worker count: check if throttle is already active from a prior run
    with _throttle_lock:
        throttled_now = _throttle_active and time.time() < _throttle_until
    workers = _MIN_WORKERS if throttled_now else MAX_PARALLEL_WORKERS

    print(f"[parallel] spawning {len(threads)} thread-summarizer agents "
          f"(max {workers} concurrent{', throttled' if throttled_now else ''})...")
    start = time.time()

    # Map index → result so we can preserve input order
    results: dict[int, dict] = {}
    failures = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {}
        for i, thread in enumerate(threads):
            future_to_idx[executor.submit(_summarize_one_thread, thread, query)] = i
            # Only sleep when throttled (rate limit was recently hit); no baseline sleep needed.
            if i < len(threads) - 1:
                stagger = _get_stagger()
                if stagger > 0:
                    time.sleep(stagger)

        completed = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            thread = threads[idx]
            subreddit = thread.get("subreddit", "?")
            try:
                summary = future.result()
                results[idx] = summary
                if summary.get("_failed"):
                    failures += 1
                    print(f"  [{completed + 1}/{len(threads)}] r/{subreddit} — FAILED, using stub")
                else:
                    n_products = len(summary.get("products_mentioned", []))
                    print(f"  [{completed + 1}/{len(threads)}] r/{subreddit} — {n_products} products extracted")
            except Exception as e:
                failures += 1
                results[idx] = {
                    "url": thread.get("url", "?"),
                    "subreddit": subreddit,
                    "thread_summary": f"(unhandled exception: {e})",
                    "products_mentioned": [],
                    "categories_mentioned": [],
                    "key_takeaways": [],
                    "top_comments": [],
                    "total_upvotes": thread.get("score", 0),
                    "controversial_signals": [],
                    "_failed": True,
                }
                print(f"  [{completed + 1}/{len(threads)}] r/{subreddit} — EXCEPTION: {e}")
            completed += 1
            if progress_callback:
                progress_callback(completed, len(threads), subreddit)

    elapsed = time.time() - start
    ordered = [results[i] for i in range(len(threads))]
    successes = len(threads) - failures
    est_sequential = elapsed / max(workers, 1) * len(threads)
    print(f"[parallel] {successes}/{len(threads)} threads summarized in {elapsed:.1f}s "
          f"(est. {est_sequential:.0f}s sequential)")
    return ordered


def format_summaries_for_main_analyzer(summaries: list[dict], max_threads: int = 10) -> str:
    """
    Format the parallel summaries into a compact text block for the main analyzer.
    Much smaller than raw threads (~30K vs 150K chars).

    Token optimisation: cap at `max_threads` (default 10) by selecting the
    highest-signal threads first.  Signal is scored by distinct product count +
    total mention count — threads that discuss many products with strong community
    signal are more useful to the main analyzer than single-product threads.
    Dropping the lowest 5 threads saves ~33% input tokens with negligible quality
    loss (their products are already covered by the richer threads).
    """
    good = [s for s in summaries if not s.get("_failed")]

    def _signal_score(s: dict) -> float:
        products = s.get("products_mentioned") or []
        product_count = len(products)
        mention_total = sum(p.get("mention_count", 0) for p in products)
        return product_count * 2.0 + mention_total

    if len(good) > max_threads:
        good = sorted(good, key=_signal_score, reverse=True)[:max_threads]

    sections = []
    for i, s in enumerate(good, 1):
        sub = s.get("subreddit", "?")
        url = s.get("url", "")
        section = [f"\n===== THREAD {i}: r/{sub} ====="]
        section.append(f"URL: {url}")
        section.append(f"Summary: {s.get('thread_summary', '')}")

        products = s.get("products_mentioned", [])
        if products:
            section.append("Products discussed:")
            for p in products[:8]:
                name = p.get("name", "?")
                sentiment = p.get("sentiment", "?")
                count = p.get("mention_count", 0)
                quotes = p.get("key_quotes", [])
                section.append(f"  • {name} [{sentiment}, mentioned {count}x]")
                for q in quotes[:2]:
                    section.append(f"      \"{q}\"")

        cats = s.get("categories_mentioned", [])
        if cats:
            section.append(f"Categories: {', '.join(cats[:5])}")

        takeaways = s.get("key_takeaways", [])
        if takeaways:
            section.append("Key takeaways:")
            for t in takeaways[:4]:
                section.append(f"  - {t}")

        ctrl = s.get("controversial_signals", [])
        if ctrl:
            section.append("Controversial signals:")
            for c in ctrl[:3]:
                section.append(f"  ! {c}")

        sections.append("\n".join(section))

    return "\n".join(sections)


def build_coref_maps_from_summaries(summaries: list[dict]) -> list[dict]:
    """
    Extract per-thread alias maps from already-computed thread summaries.

    Returns a list parallel with `summaries` where each entry is a
    {canonical_name: [alias, ...]} dict — the same format coref_pass produces.
    Passing this to run_pipeline(pre_coref_maps=...) eliminates all coref_pass
    LLM calls (typically 15 calls, ~15-30s) with zero additional API cost.

    Failed summaries (_failed=True) yield empty dicts — harmless: the registry
    will still know about those products via base_registry seeds from the main
    analysis products list.
    """
    return [s.get("aliases", {}) for s in summaries]