"""
Deep Reddit thread fetcher using PRAW (Python Reddit API Wrapper).

Activated when USE_PRAW=true and Reddit credentials are set in .env.
Returns the same shape as reddit_fetch.py so downstream code is unaffected.

Advantages over the JSON endpoint approach:
- Loads the FULL comment tree (replace_more calls) — 200-300+ comments/thread
- Comment-level metadata: awards, edit status, controversiality score
- OP-reply tagging: original asker's verdict is high-signal
- Quality scoring: top-200 by a weighted formula + top-30 controversial (deduplicated)

Rate limit: PRAW has a built-in OAuth rate limiter (~60 req/min).
We add a 1s jitter between thread fetches and use 4 workers max.
"""

import os
import re
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import cache

# Bot detection patterns — skip these comment bodies
_BOT_PATTERNS = [
    r"^I am a bot",
    r"^\*I am a bot",
    r"^This action was performed automatically",
    r"^\[deleted\]$",
    r"^\[removed\]$",
]
_BOT_RE = re.compile("|".join(_BOT_PATTERNS), re.IGNORECASE)

MAX_QUALITY_COMMENTS = 200   # top by quality score
MAX_CONTROVERSIAL = 30       # additional controversial-only comments
MAX_WORKERS = 4              # PRAW rate limit: stay well under 60 req/min
_JITTER_RANGE = (0.8, 2.0)   # seconds between per-thread fetches

# Thread-safe singleton
_reddit_lock = threading.Lock()
_reddit = None


def _praw_credentials_set() -> bool:
    return bool(
        os.environ.get("REDDIT_CLIENT_ID")
        and os.environ.get("REDDIT_CLIENT_SECRET")
        and os.environ.get("REDDIT_USER_AGENT")
    )


def get_reddit():
    global _reddit
    if _reddit is not None:
        return _reddit
    with _reddit_lock:
        if _reddit is None:
            try:
                import praw
            except ImportError:
                raise RuntimeError("praw not installed. Run: pip install praw")
            _reddit = praw.Reddit(
                client_id=os.environ["REDDIT_CLIENT_ID"],
                client_secret=os.environ["REDDIT_CLIENT_SECRET"],
                user_agent=os.environ["REDDIT_USER_AGENT"],
            )
            _reddit.read_only = True
    return _reddit


def _comment_quality_score(comment) -> float:
    """
    Weighted quality score for a PRAW comment.
    Higher = more worth including.
    """
    score = getattr(comment, "score", 0) or 0
    gilded = getattr(comment, "gilded", 0) or 0
    edited = bool(getattr(comment, "edited", False))
    body = getattr(comment, "body", "") or ""
    is_controversial = (getattr(comment, "controversiality", 0) or 0) > 0

    q = float(score)
    q += gilded * 10           # awards = community quality signal
    q += 3 if len(body) > 200 else 0    # longer = more informative
    q += 2 if edited else 0    # edited = author cared enough to revise
    q -= 5 if is_controversial else 0   # controversial flag (we track separately)
    q -= 10 if score < 0 else 0
    return q


def _flatten_all_comments(submission) -> list:
    """
    Expand MoreComments objects and return a flat list of all Comment objects.
    PRAW handles rate limiting internally.
    """
    submission.comments.replace_more(limit=None)
    return list(submission.comments.list())


def _is_junk(comment) -> bool:
    body = (getattr(comment, "body", "") or "").strip()
    if len(body) < 4:
        return True
    if _BOT_RE.search(body):
        return True
    author = getattr(comment, "author", None)
    if author is None:
        return True  # deleted/shadow account
    return False


def fetch_thread_deep(url: str, max_comments: int = 300) -> Optional[dict]:
    """
    Fetch a single Reddit thread with the FULL comment tree via PRAW.

    Returns the same shape as reddit_fetch.fetch_thread_comments(), plus:
      comments[*].depth          — nesting level (0 = top-level)
      comments[*].is_op          — True if comment is by original poster
      comments[*].is_controversial — True if controversiality > 0
      comments[*].gilded         — number of awards
      comments[*].edited         — True if comment was edited
      comments[*].parent_quote   — first 120 chars of parent body if reply
      comments_total             — Reddit's reported num_comments
      comments_captured          — actual number we're returning
      praw_fetched               — always True (signals deep fetch was used)
    """
    cached = cache.get("reddit_thread", url)
    if cached is not None:
        return cached

    reddit = get_reddit()

    try:
        submission = reddit.submission(url=url)

        op_name = str(submission.author) if submission.author else ""
        post_title = submission.title or ""
        post_body = (submission.selftext or "")[:3000]
        post_score = submission.score or 0
        subreddit = str(submission.subreddit) if submission.subreddit else ""
        num_comments_total = submission.num_comments or 0

        all_comments = _flatten_all_comments(submission)

    except Exception as exc:
        print(f"[praw] failed to fetch {url}: {exc}")
        return None

    # Build comment dicts with quality scores
    quality_pool = []
    controversial_pool = []

    for c in all_comments:
        if _is_junk(c):
            continue

        body = (c.body or "").strip()
        score = c.score or 0
        depth = getattr(c, "depth", 0) or 0
        is_op = (str(c.author) == op_name) if c.author else False
        is_controversial = (getattr(c, "controversiality", 0) or 0) > 0
        gilded = getattr(c, "gilded", 0) or 0
        edited = bool(getattr(c, "edited", False))

        # Parent quote for context on replies
        parent_quote = ""
        if depth > 0:
            try:
                parent = c.parent()
                if hasattr(parent, "body") and parent.body:
                    parent_quote = parent.body.strip()[:120]
            except Exception:
                pass

        cd = {
            "id": c.id,
            "body": body[:1500],
            "score": score,
            "depth": depth,
            "is_op": is_op,
            "is_controversial": is_controversial,
            "gilded": gilded,
            "edited": edited,
            "parent_quote": parent_quote,
        }
        qs = _comment_quality_score(c)
        quality_pool.append((qs, cd))

        if is_controversial:
            controversial_pool.append(cd)

    # Sort quality pool, take top MAX_QUALITY_COMMENTS
    quality_pool.sort(key=lambda x: -x[0])
    top_quality = [cd for _, cd in quality_pool[:MAX_QUALITY_COMMENTS]]

    # Add controversial-only comments (not already included)
    seen_ids = {cd["id"] for cd in top_quality}
    extra_controversial = []
    for cd in controversial_pool:
        if cd["id"] not in seen_ids:
            seen_ids.add(cd["id"])
            cd["from_controversial"] = True
            extra_controversial.append(cd)
            if len(extra_controversial) >= MAX_CONTROVERSIAL:
                break

    merged = top_quality + extra_controversial

    result = {
        "title": post_title,
        "subreddit": subreddit,
        "body": post_body,
        "score": post_score,
        "url": url,
        "comments": merged,
        "total_comment_count_in_thread": num_comments_total,
        "controversial_comments_added": len(extra_controversial),
        "comments_captured": len(merged),
        "praw_fetched": True,
    }

    cache.set("reddit_thread", url, result)
    return result


def fetch_threads_deep(query: str, limit: int = 15) -> list[dict]:
    """
    Orchestrate deep fetching for all URLs found by the existing URL discovery.
    Uses 4-worker pool with jitter to stay within PRAW's rate limit.
    """
    # Use existing URL discovery (Serper + Gemini) — only comment fetching changes
    from reddit_fetch import find_reddit_urls
    from reddit_fetch import detect_region

    region = detect_region(query)
    if region:
        print(f"[praw] detected region: {region}")

    print(f"[praw] discovering URLs for: {query}")
    urls = find_reddit_urls(query, limit=limit)
    for u in urls:
        print(f"   - {u}")

    results = []
    results_lock = threading.Lock()

    def _fetch_one(url: str) -> Optional[dict]:
        time.sleep(random.uniform(*_JITTER_RANGE))
        thread = fetch_thread_deep(url)
        if thread:
            captured = thread.get("comments_captured", len(thread.get("comments", [])))
            total = thread.get("total_comment_count_in_thread", "?")
            controversial = thread.get("controversial_comments_added", 0)
            extra = f" (+{controversial} controversial)" if controversial > 0 else ""
            print(f"[praw] {url}\n   → {captured} comments{extra} (of ~{total})")
        return thread

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, url): url for url in urls}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                with results_lock:
                    results.append(result)

    # Preserve original URL order
    url_order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda t: url_order.get(t.get("url", ""), 999))

    print(f"[praw] {len(results)}/{len(urls)} threads succeeded")
    return results
