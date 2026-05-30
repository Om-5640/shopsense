"""
Reddit thread fetcher (v3.1).

Improvements:
- Query variations: 3 query variants merged for consistent 15+ unique threads
- ?sort=top in JSON URL for highest-upvoted comments first
- Recursive comment tree flattening (top-level + nested replies)
- Up to 100 comments per thread (instead of 50)
- Quality filter: skip comments under 15 chars or with score <= 0
- Region awareness: respects user's currency hint (₹, $, £, €) in query
"""

import os
import re
import time
import threading as _threading
import requests
from dotenv import load_dotenv

import cache
import google_search

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.reddit.com/",
}

# Pullpush — community Reddit data API, no credentials required
_PULLPUSH = "https://api.pullpush.io/reddit"
_PULLPUSH_HEADERS = {"User-Agent": "ShopSense/1.0"}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
from models import GEMINI_MODEL, gemini_url
GEMINI_URL = gemini_url()

# Quality thresholds
MIN_COMMENT_CHARS = 4       # filters out "lol", "yep", ".", "+1" but keeps short product mentions like "Buffy" or "T310"
MIN_COMMENT_SCORE = 1       # skip downvoted or zero-score comments
MAX_COMMENTS_PER_THREAD = 100
MAX_REPLY_DEPTH = 3         # how deep to recurse into reply trees


# ---- region awareness ----

REGIONS_BY_CURRENCY = {
    "₹": "india", "rs.": "india", "rs ": "india", "inr": "india",
    "£": "uk",
    "€": "europe",
    "$": "usa",  # ambiguous (could be CAD/AUD/SGD) but USA is best default
    "¥": "japan",
    "a$": "australia",
    "c$": "canada",
}

# Words that indicate a price is mentioned (so we know to ask about currency)
PRICE_INDICATORS = ["under", "below", "around", "max", "budget", "less than", "for", "upto", "up to", "within"]


def detect_region(query: str) -> str | None:
    """Returns region key. Checks thread-local session override first, then currency in query."""
    override = getattr(_session_local, "region", None)
    if override:
        return override
    q = query.lower()
    for marker, region in REGIONS_BY_CURRENCY.items():
        if marker in q:
            return region
    return None


# Thread-local region override — each pipeline thread has its own isolated value.
# Replaces the old module-level global which caused cross-request corruption under concurrency.
_session_local = _threading.local()


def set_session_region(region: str) -> None:
    """Set the region for the current pipeline thread. Thread-safe — no global state."""
    _session_local.region = region if region != "global" else None


def has_ambiguous_price(query: str) -> bool:
    """
    True if the query mentions a price-like number with NO currency marker.
    E.g. "best watch under 5000" → True (could be $5000 or ₹5000)
    E.g. "best watch under ₹5000" → False (currency known)
    E.g. "best watch for me" → False (no price mentioned)
    """
    if detect_region(query) is not None:
        return False  # currency is explicit

    q = query.lower()
    # Look for a price indicator followed by a number, or "Nk" / "N000"+
    has_indicator = any(ind in q for ind in PRICE_INDICATORS)
    has_number = bool(re.search(r"\b\d{2,}k?\b", q))
    return has_indicator and has_number


def resolve_region_interactively(query: str, profile: dict | None = None) -> tuple[str, str]:
    """
    Returns (region_key, updated_query).
    If region is already detectable, returns it unchanged.
    If profile has a saved region for this category, reuses it silently.
    Otherwise asks the user once, persists the choice in the profile.
    """
    # 1. Already detectable from query
    region = detect_region(query)
    if region is not None:
        return region, query

    # 2. Profile remembers a region for this category
    if profile and profile.get("region"):
        saved = profile["region"]
        print(f"[region] using saved region: {saved}")
        return saved, query

    # 3. Ambiguous price - ask the user
    if has_ambiguous_price(query):
        print(f"\n{'─'*72}")
        print("  CURRENCY CHECK")
        print(f"  Your query has a price but no currency symbol.")
        print(f"  Which region/currency are you shopping in?")
        print(f"{'─'*72}")
        print("    1. India (₹)")
        print("    2. USA ($)")
        print("    3. UK (£)")
        print("    4. Europe (€)")
        print("    5. Canada (C$)")
        print("    6. Australia (A$)")
        print("    7. Other / no specific region")
        try:
            choice = input("Choose (1-7) [default 1=India]: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"

        mapping = {
            "1": "india", "2": "usa", "3": "uk", "4": "europe",
            "5": "canada", "6": "australia", "7": "global",
        }
        region = mapping.get(choice, "india")
        print(f"[region] using: {region}")
        return region, query

    # 4. No price, no currency → no region needed
    return "global", query


import re  # needed for has_ambiguous_price


# Usage-pattern keywords → short label injected into query variant
_USAGE_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["gaming", "game", "fps", "esports", "ps5", "xbox"], "gaming"),
    (["gym", "workout", "exercise", "running", "fitness", "sports"], "gym workout"),
    (["commut", "transit", "bus", "train", "office", "daily use"], "commuting"),
    (["studio", "recording", "music production", "mixing", "daw"], "studio"),
    (["audiophile", "hi-fi", "hifi", "lossless", "dac"], "audiophile"),
    (["sleep", "sleeping", "bedtime", "night"], "sleeping"),
    (["travel", "flight", "airplane", "portable"], "travel"),
]


def _extract_usage_pattern(profile: dict | None) -> str | None:
    """Return first recognized usage pattern from intent.preferences or preferences_summary."""
    if not profile:
        return None
    intent = profile.get("intent")
    if intent and isinstance(intent, dict):
        text = " ".join(intent.get("preferences", []))
    else:
        text = ""
    text = (text or profile.get("preferences_summary") or "").lower()
    if not text:
        return None
    for keywords, label in _USAGE_KEYWORD_MAP:
        if any(kw in text for kw in keywords):
            return label
    return None


def _query_variations(query: str, profile: dict | None = None) -> list[str]:
    """
    Generate semantically diverse query variants to broaden the thread pool.
    Profile-aware: injects usage pattern (gaming/gym/commute…) and budget term
    as additional variants so Reddit threads relevant to the user's actual context
    surface in the results.
    """
    region = detect_region(query)
    variations = [
        f"site:reddit.com {query}",
        f"site:reddit.com {query} recommendation",
        f"site:reddit.com {query} review",
        f"site:reddit.com {query} vs",
    ]

    # Usage-pattern semantic variant (e.g. "…gaming", "…gym workout")
    usage = _extract_usage_pattern(profile)
    if usage:
        variations.append(f"site:reddit.com {query} {usage}")

    # Budget-explicit variant when user has a stated budget
    intent = (profile or {}).get("intent") if isinstance(profile, dict) else None
    budget_str = intent.get("budget") if isinstance(intent, dict) else None
    if budget_str:
        variations.append(f"site:reddit.com {query} budget")

    # Region-targeted variant for localized advice threads
    if region == "india":
        variations.append(f"site:reddit.com {query} india")
    elif region == "uk":
        variations.append(f"site:reddit.com {query} uk")
    elif region == "australia":
        variations.append(f"site:reddit.com {query} australia")
    elif region in ("usa", "canada"):
        variations.append(f"site:reddit.com {query} worth it")
    return variations


# ---- URL discovery ----

def find_reddit_urls(query: str, limit: int = 15, profile: dict | None = None) -> list[str]:
    """Find Reddit URLs using multiple query variants merged + deduped."""
    cache_key = f"urls|{query}|{limit}"
    cached = cache.get("reddit_urls", cache_key)
    if cached is not None:
        print(f"[reddit] URL cache hit for: {query}")
        return cached

    all_urls = []
    variations = _query_variations(query, profile)
    region = detect_region(query)

    # Source 1: Serper (primary) — run all query variations
    # Track which variant each URL came from so region-specific variants get bonus
    url_to_variant_idx = {}
    if google_search.is_configured():
        for variant_idx, variant in enumerate(variations):
            urls = google_search.search(variant, num=10)
            for r in urls:
                link = r.get("link", "")
                if "reddit.com" in link and "/comments/" in link:
                    norm = _normalize_reddit_url(link)
                    if norm and norm not in url_to_variant_idx:
                        url_to_variant_idx[norm] = variant_idx
                        all_urls.append(norm)
        print(f"[reddit] serper: {len(all_urls)} raw URLs from {len(variations)} variants")

    # Source 2: Gemini grounding fallback (only if Serper returns too few)
    if len(all_urls) < limit:
        grounding_urls = _find_via_gemini_grounding(query, limit)
        for u in grounding_urls:
            norm = _normalize_reddit_url(u)
            if norm and norm not in url_to_variant_idx:
                url_to_variant_idx[norm] = 999  # lower-priority source
                all_urls.append(norm)
        print(f"[reddit] gemini grounding fallback: {len(grounding_urls)} URLs")

    if not all_urls:
        cache.set("reddit_urls", cache_key, [])
        return []

    # ---- Quality scoring: pick the best `limit` threads, not just first `limit` ----
    print(f"[reddit] scoring {len(all_urls)} URLs to pick top {limit} by quality...")
    scored_urls = _score_and_rank_urls(all_urls, query, region, url_to_variant_idx)

    # Take top N by score
    result = [url for url, _ in scored_urls[:limit]]
    print(f"[reddit] {len(result)} top-quality URLs selected:")
    for url, score in scored_urls[:limit]:
        print(f"   [score={score:.1f}] {url}")

    cache.set("reddit_urls", cache_key, result)
    return result


def _score_and_rank_urls(urls: list[str], query: str, region: str | None,
                          variant_idx_map: dict) -> list[tuple]:
    """
    Score each URL by:
    - Subreddit relevance (region match, generic-relevance)
    - URL-text match to query keywords
    - Variant source priority (earlier variant = higher quality match)
    Returns list of (url, score) sorted by score descending.
    """
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    query_tokens -= {"best", "good", "the", "for", "under", "below", "around",
                     "reddit", "review", "site", "buy", "to", "of", "in", "a", "an"}

    # Region-aware subreddit weighting
    region_subs = _region_subreddits(region)

    scored = []
    for url in urls:
        score = 0.0

        # Extract subreddit from URL
        match = re.search(r"/r/([^/]+)/", url)
        subreddit = match.group(1).lower() if match else ""

        # 1. Region subreddit bonus (huge — Indian sub for Indian query)
        if subreddit in region_subs.get("primary", set()):
            score += 50.0  # very strong signal
        elif subreddit in region_subs.get("secondary", set()):
            score += 15.0

        # 2. Title relevance: count query tokens in the URL TITLE SLUG only
        # (Not the full URL — subreddit name like "/r/Watches/" would always match "watch")
        # Reddit slugs use underscores, so split on word chars (excluding _)
        slug_match = re.search(r"/comments/[^/]+/([^/?#]+)", url.lower())
        title_slug = slug_match.group(1) if slug_match else ""
        title_tokens = set(re.findall(r"[a-z0-9]+", title_slug))
        token_overlap = len(query_tokens & title_tokens)
        score += token_overlap * 5.0

        # 3. Variant source priority (variant 0 = main query, weighted higher)
        variant = variant_idx_map.get(url, 999)
        if variant == 0:
            score += 10.0  # main query result
        elif variant <= 2:
            score += 5.0   # other variants
        elif variant == 3:
            score += 8.0   # region-specific variant (also valuable)

        # 4. Penalty for obviously off-topic subreddits
        off_topic = {"phoenix", "askreddit", "outoftheloop"}
        if region == "india" and subreddit in off_topic:
            score -= 15.0

        scored.append((url, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _region_subreddits(region: str | None) -> dict:
    """Map region to primary and secondary subreddits we want to prioritize."""
    if region == "india":
        return {
            "primary": {
                "watchesindia", "indiansocial", "indiasocial", "buyitforlifeindia",
                "indiatech", "gadgetsindia", "headphonesindia", "smartphonesindia",
                "chennai", "bangalore", "mumbai", "delhi", "kolkata", "hyderabad",
                "kochi", "indianbikes", "indianstreetbets",
            },
            "secondary": set(),
        }
    elif region == "uk":
        return {
            "primary": {
                "ukpersonalfinance", "casualuk", "unitedkingdom", "britishproblems",
                "buyitforlifeuk",
            },
            "secondary": set(),
        }
    elif region == "australia":
        return {
            "primary": {"australia", "ausfinance", "askanaustralian", "ozbargain"},
            "secondary": set(),
        }
    elif region == "canada":
        return {
            "primary": {"canada", "personalfinancecanada", "askacanadian"},
            "secondary": set(),
        }
    else:  # usa / global
        return {
            "primary": set(),  # no specific region to favor
            "secondary": set(),
        }


def _find_via_gemini_grounding(query: str, limit: int) -> list[str]:
    if not GEMINI_API_KEY:
        return []

    prompt = (
        f"Search Google for: site:reddit.com {query}\n\n"
        f"List the top {limit} Reddit thread URLs you find."
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }

    try:
        resp = _gemini_request(body)
    except Exception as e:
        print(f"[reddit] gemini grounding failed (non-fatal): {e}")
        return []

    data = resp.json()
    return _extract_urls_from_grounding(data)


def _gemini_request(body, max_attempts=3, wait=10):
    last_err = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(
                GEMINI_URL,
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                print(f"[reddit] gemini attempt {attempt + 1} failed. Retrying in {wait}s...")
                time.sleep(wait)
    raise last_err


def _extract_urls_from_grounding(data: dict) -> list[str]:
    urls = []
    try:
        grounding = data["candidates"][0].get("groundingMetadata", {})
        for chunk in grounding.get("groundingChunks", []):
            uri = (chunk.get("web") or {}).get("uri") or ""
            if not uri:
                continue
            if "reddit.com" in uri:
                urls.append(uri)
            else:
                try:
                    r = requests.head(uri, allow_redirects=True, timeout=10,
                                      headers={"User-Agent": HEADERS["User-Agent"]})
                    if "reddit.com" in r.url:
                        urls.append(r.url)
                except Exception:
                    pass
    except (KeyError, IndexError):
        pass
    return urls


def _normalize_reddit_url(url: str) -> str:
    url = url.split("?")[0].split("#")[0].rstrip("/")
    url = url.replace("https://reddit.com", "https://www.reddit.com")
    url = url.replace("http://", "https://")
    if "reddit.com/r/" not in url or "/comments/" not in url:
        return ""
    return url


# ---- thread content fetching ----

def _flatten_comment_tree(comments_raw: list, depth: int = 0) -> list[dict]:
    """
    Recursively walk Reddit's nested comment tree and return a flat list.
    Carries the Reddit comment ID for deduplication across sort passes.
    Stops at MAX_REPLY_DEPTH to avoid runaway recursion.
    """
    out = []
    if depth > MAX_REPLY_DEPTH:
        return out

    for c in comments_raw:
        kind = c.get("kind")
        if kind != "t1":  # only actual comments, skip "more" placeholders
            continue
        cd = c.get("data", {})
        body = cd.get("body")
        score = cd.get("score", 0)
        comment_id = cd.get("id", "")  # Reddit's unique comment ID

        if body and body not in ("[deleted]", "[removed]"):
            # Quality filter: skip junk
            if len(body.strip()) >= MIN_COMMENT_CHARS and score >= MIN_COMMENT_SCORE:
                out.append({
                    "id": comment_id,
                    "body": body[:1500],
                    "score": score,
                    "depth": depth,
                })

        # Recurse into replies
        replies = cd.get("replies")
        if replies and isinstance(replies, dict):
            reply_children = replies.get("data", {}).get("children", [])
            if reply_children:
                out.extend(_flatten_comment_tree(reply_children, depth=depth + 1))

    return out


def _fetch_raw_comments(permalink: str, sort: str, limit: int) -> list:
    """Fetch raw comment children from Reddit for a given sort. Returns [] on failure."""
    json_url = permalink.rstrip("/") + f"/.json?sort={sort}&limit={limit}"
    for attempt in range(3):
        try:
            resp = requests.get(json_url, headers=HEADERS, timeout=15)
            if resp.status_code == 429:
                raise requests.HTTPError("429 Rate Limited")
            resp.raise_for_status()
            data = resp.json()
            return data[1]["data"]["children"]
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
            else:
                print(f"   [{sort} sort] failed: {e}")
    return []


def _extract_post_id(permalink: str) -> "str | None":
    m = re.search(r"/comments/([a-z0-9]+)/", permalink)
    return m.group(1) if m else None


def _pullpush_fetch_thread(permalink: str, max_comments: int) -> "dict | None":
    """Fetch thread via Pullpush.io — no Reddit credentials needed, bypasses Cloudflare."""
    post_id = _extract_post_id(permalink)
    if not post_id:
        return None
    try:
        resp = requests.get(
            f"{_PULLPUSH}/search/submission/?ids={post_id}",
            headers=_PULLPUSH_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", [])
        if not posts:
            return None
        post = posts[0]

        resp2 = requests.get(
            f"{_PULLPUSH}/search/comment/?link_id={post_id}"
            f"&limit={max_comments}&sort_type=score&order=desc",
            headers=_PULLPUSH_HEADERS, timeout=20,
        )
        resp2.raise_for_status()
        raw_comments = resp2.json().get("data", [])

        comments = []
        seen_ids: set = set()
        for c in raw_comments:
            body = (c.get("body") or "").strip()
            if not body or body in ("[deleted]", "[removed]"):
                continue
            if len(body) < MIN_COMMENT_CHARS:
                continue
            score = c.get("score", 0) or 0
            if score < MIN_COMMENT_SCORE:
                continue
            cid = c.get("id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            comments.append({
                "id": cid,
                "body": body[:1500],
                "score": score,
                "depth": 0,
                "from_controversial": bool((c.get("controversiality") or 0) > 0),
            })

        controversial_count = sum(1 for c in comments if c.get("from_controversial"))
        return {
            "title": post.get("title", ""),
            "subreddit": post.get("subreddit", ""),
            "body": (post.get("selftext") or "")[:3000],
            "score": post.get("score", 0),
            "url": permalink,
            "comments": comments,
            "total_comment_count_in_thread": post.get("num_comments", 0),
            "controversial_comments_added": controversial_count,
        }
    except Exception as e:
        print(f"[reddit] pullpush failed for {permalink}: {e}")
        return None


def fetch_thread_comments(permalink: str, max_comments: int = MAX_COMMENTS_PER_THREAD) -> dict | None:
    """Fetch thread JSON.

    Two-pass comment strategy:
    1. sort=top    → highest-upvoted comments (consensus, recommendations)
    2. sort=controversial → heavily debated comments (complaints, disagreements)

    Merged by Reddit comment ID — no duplicates. Top-sort comments keep their
    position. Controversial-only comments appended after, sorted by score.
    This ensures we never miss complaints buried in controversy.
    """
    cached = cache.get("reddit_thread", permalink)
    if cached is not None:
        return cached

    # ---- Primary: Pullpush (no credentials, bypasses Reddit Cloudflare) ----
    result = _pullpush_fetch_thread(permalink, max_comments)
    if result is not None:
        cache.set("reddit_thread", permalink, result)
        return result

    # ---- Fallback: direct Reddit JSON endpoint ----
    json_url = permalink.rstrip("/") + f"/.json?sort=top&limit={max_comments}"
    last_err = None
    post_data = None
    for attempt in range(3):
        try:
            resp = requests.get(json_url, headers=HEADERS, timeout=15)
            if resp.status_code == 429:
                raise requests.HTTPError("429 Rate Limited")
            resp.raise_for_status()
            raw = resp.json()
            post_data = raw[0]["data"]["children"][0]["data"]
            top_raw = raw[1]["data"]["children"]
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"   retry in {wait}s ({e})")
                time.sleep(wait)

    if post_data is None:
        print(f"[reddit] giving up on {permalink}: {last_err}")
        return None

    # Pass 1: flatten top-sorted comments
    top_comments = _flatten_comment_tree(top_raw)

    # Pass 2: fetch controversial sort, flatten, merge by ID
    # Small delay to avoid rate limiting
    time.sleep(0.5)
    controversial_raw = _fetch_raw_comments(permalink, "controversial", max_comments)
    controversial_comments = _flatten_comment_tree(controversial_raw)

    # Merge: top-sort comments first (preserve order), then add any
    # controversial-only comments not already seen (by Reddit comment ID)
    seen_ids = set()
    merged = []

    for c in top_comments:
        cid = c.get("id", "")
        if cid:
            seen_ids.add(cid)
        merged.append(c)

    controversial_only = []
    for c in controversial_comments:
        cid = c.get("id", "")
        # Skip if already in top sort OR if no ID (can't dedup safely)
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            # Tag so analyzer knows this came from controversial sort
            c["from_controversial"] = True
            controversial_only.append(c)

    # Sort controversial-only additions by score before appending
    controversial_only.sort(key=lambda c: c["score"], reverse=True)
    merged.extend(controversial_only)

    # Final cap
    merged = merged[:max_comments]

    result = {
        "title": post_data.get("title", ""),
        "subreddit": post_data.get("subreddit", ""),
        "body": (post_data.get("selftext") or "")[:3000],
        "score": post_data.get("score", 0),
        "url": permalink,
        "comments": merged,
        "total_comment_count_in_thread": post_data.get("num_comments", 0),
        "controversial_comments_added": len(controversial_only),
    }

    cache.set("reddit_thread", permalink, result)
    return result


def _praw_credentials_set() -> bool:
    return bool(
        os.environ.get("REDDIT_CLIENT_ID")
        and os.environ.get("REDDIT_CLIENT_SECRET")
        and os.environ.get("REDDIT_USER_AGENT")
    )


def fetch_all_threads(
    query: str,
    limit: int = 15,
    delay: float = 1.5,
    profile: dict | None = None,
) -> list[dict]:
    """
    End-to-end fetch.
    If USE_PRAW=true and Reddit credentials are set, uses the PRAW deep fetcher
    (200+ comments/thread). Otherwise falls back to the JSON endpoint approach.
    `profile` is forwarded to _query_variations for intent-aware semantic variants.
    """
    if os.environ.get("USE_PRAW", "").lower() == "true" and _praw_credentials_set():
        from reddit_praw import fetch_threads_deep
        return fetch_threads_deep(query, limit=limit)

    region = detect_region(query)
    if region:
        print(f"[reddit] detected region: {region}")

    print(f"[reddit] discovering URLs for: {query}")
    urls = find_reddit_urls(query, limit=limit, profile=profile)
    for u in urls:
        print(f"   - {u}")

    enriched = []
    for i, url in enumerate(urls, 1):
        print(f"[reddit] fetching {i}/{len(urls)}: {url}")
        full = fetch_thread_comments(url)
        if full is not None:
            enriched.append(full)
            total = full.get('total_comment_count_in_thread', '?')
            controversial_added = full.get('controversial_comments_added', 0)
            extra = f" (+{controversial_added} controversial)" if controversial_added > 0 else ""
            print(f"   got {len(full['comments'])} quality comments{extra} (out of ~{total} total)")
        time.sleep(delay)
    print(f"[reddit] {len(enriched)}/{len(urls)} threads succeeded")
    return enriched