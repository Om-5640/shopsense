"""
Review site fetcher.

Strategy:
1. Use Gemini grounding to find review/article URLs for the query
2. Scrape each URL with BeautifulSoup, extracting main content
3. Handle failures gracefully - any site can fail, we keep what works

No site-specific selectors. We try standard semantic HTML and fall back
to "biggest text block" heuristic.
"""

import os
import re
import time
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import cache
import domain_blacklist as _db

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
from models import GEMINI_MODEL, gemini_url
GEMINI_URL = gemini_url()

# Rotate through user agents to reduce bot detection
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_ua_idx = 0

def _next_ua() -> str:
    global _ua_idx
    ua = _USER_AGENTS[_ua_idx % len(_USER_AGENTS)]
    _ua_idx += 1
    return ua

def _scraper_headers() -> dict:
    return {
        "User-Agent": _next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

# Keep one static dict for redirect resolution (no sec-fetch headers there)
SCRAPER_HEADERS = {"User-Agent": _USER_AGENTS[0], "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

# BLOCKED_DOMAINS is now managed by domain_blacklist.py (auto-updated on failure)

MAX_CONTENT_CHARS = 10_000

# Jina Reader — renders JS-heavy pages server-side, returns clean markdown
_JINA_BASE = "https://r.jina.ai"
_JINA_HEADERS = {
    "User-Agent": "ShopSense/1.0",
    "Accept": "text/plain",
    "X-Return-Format": "markdown",
    "X-Timeout": "15",
}


# ---- find review URLs ----

def find_review_urls_via_gemini(query: str, limit: int = 10) -> list[str]:
    """Use Gemini grounding to find non-Reddit review/article URLs.
    Gemini's Google Search grounding discovers the best current sources for any query dynamically.
    No hardcoded site lists — grounding knows what's authoritative for each product type."""
    if not GEMINI_API_KEY:
        return []

    cache_key = f"reviews|{query}|{limit}"
    cached = cache.get("review_urls", cache_key)
    if cached is not None:
        print(f"[reviews] cache hit for: {query}")
        return cached

    from reddit_fetch import detect_region
    region = detect_region(query)

    region_clause = ""
    if region == "india":
        region_clause = (
            "\n- This is an Indian market query (₹/Rs). Prioritize sources that cover "
            "India-available models with ₹ pricing. Include Indian tech/review publications "
            "alongside global authorities. Exclude US-only sources unless they explicitly cover "
            "Indian-market availability."
        )
    elif region == "uk":
        region_clause = (
            "\n- This is a UK market query (£). Prioritize UK-focused sources with £ pricing "
            "and UK model availability. Avoid US-only sources."
        )
    elif region == "europe":
        region_clause = (
            "\n- This is a European market query (€). Prioritize European sources covering "
            "EU availability and € pricing."
        )
    elif region == "australia":
        region_clause = (
            "\n- This is an Australian market query (A$). Prioritize Australian sources "
            "covering AU availability and A$ pricing."
        )
    elif region == "canada":
        region_clause = (
            "\n- This is a Canadian market query (C$). Prioritize Canadian sources "
            "covering CA availability and C$ pricing."
        )

    prompt = (
        f"Find the top {limit} most authoritative review articles and buying guides for: {query}\n\n"
        f"Requirements:\n"
        f"- Expert or professional reviews with hands-on testing, not spec summaries or listicles\n"
        f"- From specialist publications, trusted review outlets, or well-regarded enthusiast communities\n"
        f"- Recent content (2023–2025) covering current models\n"
        f"- Diverse sources: mix of mainstream press and specialist/niche review sites\n"
        f"- Exclude: Reddit, YouTube, Instagram, TikTok, Amazon/Flipkart listings, social media\n"
        f"- Exclude thin affiliate blogs and generic keyword-stuffed SEO aggregators{region_clause}\n\n"
        f"Use search to find the best currently active, most trusted review sources for this "
        f"specific product type and return their direct article URLs."
    )

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }

    try:
        resp = _gemini_request(body)
    except Exception as e:
        print(f"[reviews] gemini failed: {e}")
        return []

    data = resp.json()
    urls = _extract_urls_from_grounding(data)

    # Filter out blocked domains + Reddit
    clean = []
    seen = set()
    for u in urls:
        u = _normalize_url(u)
        if not u:
            continue
        domain = urlparse(u).netloc.lower().replace("www.", "")
        if _db.is_blacklisted(domain):
            continue
        if "reddit.com" in domain:
            continue
        if u in seen:
            continue
        seen.add(u)
        clean.append(u)

    result = clean[:limit]
    cache.set("review_urls", cache_key, result)
    print(f"[reviews] found {len(result)} review URLs")
    return result


def _gemini_request(body, max_attempts=3, wait=10):
    last_err = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(
                GEMINI_URL,
                headers={"Content-Type": "application/json"},
                params={"key": GEMINI_API_KEY},
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                print(f"[reviews] gemini attempt {attempt + 1} failed. Retrying in {wait}s...")
                time.sleep(wait)
    raise last_err


def _extract_urls_from_grounding(data: dict) -> list[str]:
    """Extract real URLs from grounding metadata, resolving redirects."""
    urls = []
    try:
        grounding = data["candidates"][0].get("groundingMetadata", {})
        for chunk in grounding.get("groundingChunks", []):
            uri = (chunk.get("web") or {}).get("uri") or ""
            if not uri:
                continue
            # Resolve grounding redirect URLs
            if "vertexaisearch" in uri or "googleapis.com" in uri:
                try:
                    r = requests.head(uri, allow_redirects=True, timeout=10,
                                      headers={"User-Agent": SCRAPER_HEADERS["User-Agent"]})
                    final = r.url
                    if final.startswith("http"):
                        urls.append(final)
                except Exception:
                    pass
            else:
                urls.append(uri)
    except (KeyError, IndexError):
        pass
    return urls


def _normalize_url(url: str) -> str:
    url = url.split("#")[0].rstrip("/")
    if not url.startswith("http"):
        return ""
    return url


# ---- scrape page content ----

def _fetch_via_jina(url: str) -> str | None:
    """Fetch page via Jina Reader — handles JS-heavy sites and some 403 blocks."""
    try:
        resp = requests.get(
            f"{_JINA_BASE}/{url}",
            headers=_JINA_HEADERS,
            timeout=25,
        )
        if resp.status_code == 200:
            text = resp.text.strip()
            if len(text) > 300:
                return text[:MAX_CONTENT_CHARS]
    except Exception:
        pass
    return None


def fetch_review_page(url: str) -> dict | None:
    """Scrape a single review page. Returns {url, domain, title, content} or None on failure."""
    domain = urlparse(url).netloc.lower().replace("www.", "")

    if _db.is_blacklisted(domain):
        print(f"[scrape] skipping blacklisted domain: {domain}")
        return None

    # Check cache first
    cached = cache.get("review_page", url)
    if cached is not None:
        return cached

    raw_html_ok = True
    try:
        resp = requests.get(url, headers=_scraper_headers(), timeout=15)
        if resp.status_code == 403 or resp.status_code == 401:
            print(f"[scrape] {resp.status_code} for {url}, trying Jina Reader...")
            raw_html_ok = False
        elif resp.status_code >= 400:
            print(f"[scrape] {resp.status_code} for {url}")
            _db.record_failure(domain, status_code=resp.status_code)
            return None
        else:
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
    except Exception as e:
        print(f"[scrape] failed {url}: {e}")
        raw_html_ok = False

    result = None
    if raw_html_ok:
        try:
            result = _extract_content(html, url)
        except Exception as e:
            print(f"[scrape] parse error {url}: {e}")

    # Fallback to Jina Reader for JS-heavy sites or 403 blocks
    if not result or len(result["content"]) < 300:
        jina_content = _fetch_via_jina(url)
        if jina_content:
            from source_filter import get_authority_tier
            title = url.split("/")[-1].replace("-", " ").replace("_", " ")
            result = {
                "url": url,
                "domain": domain,
                "title": title[:300],
                "content": jina_content,
                "authority_tier": get_authority_tier(url),
            }
            print(f"[scrape] Jina Reader succeeded for {domain}")
        else:
            print(f"[scrape] too little content from {url} (paywall/JS, Jina also failed)")
            _db.record_failure(domain)
            return None

    _db.record_success(domain)
    cache.set("review_page", url, result)
    return result


def _extract_content(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    # Remove junk
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "form", "iframe", "noscript", "button"]):
        tag.decompose()

    # Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    # Content - try semantic tags, then biggest div
    content = ""
    for selector in ["article", "main", "[role='main']"]:
        node = soup.select_one(selector)
        if node:
            content = node.get_text(separator="\n", strip=True)
            if len(content) > 500:
                break

    if len(content) < 500:
        # Fall back: find the div with the most text
        candidates = soup.find_all("div")
        best = ""
        for div in candidates:
            text = div.get_text(separator="\n", strip=True)
            if len(text) > len(best):
                best = text
        content = best

    # Clean up whitespace
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]+", " ", content)
    content = content[:MAX_CONTENT_CHARS]

    if not content:
        return None

    domain = urlparse(url).netloc.lower().replace("www.", "")

    from source_filter import get_authority_tier
    return {
        "url": url,
        "domain": domain,
        "title": title[:300],
        "content": content,
        "authority_tier": get_authority_tier(url),
    }


def _find_review_urls_via_serper(query: str, limit: int) -> list[str]:
    """Serper fallback for review URL discovery when Gemini grounding fails.
    Uses a dynamic search query — no hardcoded site lists. Google ranking surfaces
    the best current sources naturally."""
    import google_search
    if not google_search.is_configured():
        return []

    from reddit_fetch import detect_region
    region = detect_region(query)

    region_term = {
        "india": " india",
        "uk": " uk",
        "europe": " europe",
        "australia": " australia",
        "canada": " canada",
    }.get(region or "", "")

    search_query = f"{query}{region_term} expert review buying guide"
    results = google_search.search(search_query, num=limit * 2)

    urls = []
    seen = set()
    for r in results:
        link = r.get("link", "")
        if not link or "reddit.com" in link or link in seen:
            continue
        seen.add(link)
        urls.append(link)

    print(f"[reviews] serper fallback ({region or 'global'}): {len(urls[:limit])} review URLs")
    return urls[:limit]


def fetch_all_reviews(query: str, limit: int = 10, delay: float = 1.0) -> list[dict]:
    """End-to-end: find review URLs, filter junk, scrape each, return what worked.
    Primary: Gemini grounding (knows authoritative sites per category)
    Fallback: Serper search for review sites (when Gemini quota is hit)
    """
    from source_filter import filter_review_urls

    urls = find_review_urls_via_gemini(query, limit=limit)

    # Serper fallback if Gemini returned nothing
    if not urls:
        print("[reviews] Gemini returned 0 URLs, trying Serper fallback...")
        urls = _find_review_urls_via_serper(query, limit=limit)

    if not urls:
        print("[reviews] no review URLs found from any source")
        return []

    # Filter affiliate junk — conservative, whitelist always wins
    urls = filter_review_urls(urls)
    if not urls:
        print("[reviews] all URLs filtered as junk — check source_filter.py whitelist")
        return []

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[scrape] {i}/{len(urls)}: {url}")
        page = fetch_review_page(url)
        if page:
            results.append(page)
        time.sleep(delay)
    print(f"[scrape] {len(results)}/{len(urls)} succeeded")
    return results