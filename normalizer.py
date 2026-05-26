"""
Source normalizer.

Takes outputs from reddit_fetch and review_fetch and unifies them into
a single shape the analyzer can iterate over without special cases.
"""


def normalize_reddit_thread(thread: dict) -> dict:
    """Reddit thread → common format. Includes depth so analyzer can distinguish
    top-level comments from nested replies."""
    return {
        "source_type": "reddit",
        "source_name": f"r/{thread.get('subreddit', 'unknown')}",
        "url": thread.get("url", ""),
        "title": thread.get("title", ""),
        "body": thread.get("body", "") or "",
        "discussions": [
            {
                "text": c["body"],
                "score": c.get("score", 0),
                "depth": c.get("depth", 0),
                "controversial": c.get("from_controversial", False),
            }
            for c in thread.get("comments", [])
        ],
        "score": thread.get("score", 0),
    }


def normalize_review_page(page: dict) -> dict:
    """Review page → common format. Carries authority tier for weighted analysis."""
    return {
        "source_type": "review",
        "source_name": page.get("domain", "unknown"),
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "body": page.get("content", "") or "",
        "discussions": [],
        "score": 0,
        "authority_tier": page.get("authority_tier", "unknown"),
    }


def normalize_all(reddit_threads: list[dict], review_pages: list[dict]) -> list[dict]:
    """Combine both into one list. Reddit first (higher signal weight)."""
    out = []
    for t in reddit_threads:
        out.append(normalize_reddit_thread(t))
    for p in review_pages:
        out.append(normalize_review_page(p))
    return out