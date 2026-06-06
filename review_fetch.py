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
# bs4 is imported lazily inside _extract_content() so this module stays importable
# (e.g. for _fetch_via_jina, which needs no HTML parsing) even when bs4 is absent.
from dotenv import load_dotenv

import cache
import domain_blacklist as _db
from reddit_fetch import detect_region

# Phase 1–9 enhancement modules — all optional; failures are non-fatal.
try:
    from review_extractor import extract_review_structure as _extract_structure
    _HAS_EXTRACTOR = True
except Exception:
    _HAS_EXTRACTOR = False

try:
    from review_freshness import extract_article_date as _extract_date, compute_freshness_score as _freshness
    _HAS_FRESHNESS = True
except Exception:
    _HAS_FRESHNESS = False

try:
    from domain_trust import get_domain_trust_score as _trust_score
    _HAS_TRUST = True
except Exception:
    _HAS_TRUST = False

try:
    from review_ranker import compute_review_rank_score as _rank_score
    _HAS_RANKER = True
except Exception:
    _HAS_RANKER = False

try:
    from contradiction_detector import detect_review_conflicts as _detect_conflicts
    _HAS_CONTRADICTION = True
except Exception:
    _HAS_CONTRADICTION = False

try:
    from review_candidates import retrieve_review_candidates as _retrieve_candidates
    _HAS_CANDIDATES = True
except Exception:
    _HAS_CANDIDATES = False

try:
    from youtube_review_fetch import fetch_youtube_reviews as _fetch_youtube
    _HAS_YOUTUBE = True
except Exception:
    _HAS_YOUTUBE = False

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

# Sites that always fail direct HTTP (anti-bot JS rendering, paywall headers).
# We skip the raw HTTP attempt entirely and go straight to Jina, saving ~15s per URL.
_KNOWN_JS_HEAVY = frozenset({
    "pcmag.com", "techradar.com", "cnet.com", "tomsguide.com",
    "tomshardware.com", "digitaltrends.com", "zdnet.com",
    "wired.com", "theverge.com", "engadget.com",
    "9to5mac.com", "9to5google.com", "macrumors.com",
})

# Data-rich sites that require a longer Jina server-side render timeout.
# rtings.com pages are very large (spec tables, charts); 15s is consistently insufficient.
_JINA_LONG_TIMEOUT_DOMAINS = frozenset({
    "rtings.com", "notebookcheck.net", "gsmarena.com",
    "dxomark.com", "phonearena.com",
})


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
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
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
    """Fetch page via Jina Reader — handles JS-heavy sites and some 403 blocks.

    Adaptive timeout: data-rich domains (rtings.com, gsmarena.com…) get 35s client
    timeout and tell Jina's server to wait up to 28s; all others use 25s / 15s.
    """
    domain = urlparse(url).netloc.lower().replace("www.", "")
    if domain in _JINA_LONG_TIMEOUT_DOMAINS:
        client_timeout = 40
        server_timeout = "30"   # X-Timeout sent to Jina
    else:
        client_timeout = 25
        server_timeout = "15"

    headers = {**_JINA_HEADERS, "X-Timeout": server_timeout}
    try:
        resp = requests.get(
            f"{_JINA_BASE}/{url}",
            headers=headers,
            timeout=client_timeout,
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

    # Skip direct HTTP for known JS-heavy / anti-bot domains — saves ~15s wasted attempt.
    # These sites require server-side JS rendering that Jina provides.
    raw_html_ok = domain not in _KNOWN_JS_HEAVY
    if not raw_html_ok:
        print(f"[scrape] {domain}: known JS-heavy, skipping direct HTTP → Jina only")
    html = ""
    if raw_html_ok:
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
        # Phase 2: preserve any date extracted from original HTML before overwriting result
        _prior_pub_date = (result or {}).get("published_date")
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
                "published_date": _prior_pub_date,  # carry date from original HTML if found
            }
            print(f"[scrape] Jina Reader succeeded for {domain}")
        else:
            print(f"[scrape] too little content from {url} (paywall/JS, Jina also failed)")
            _db.record_failure(domain)
            return None

    _db.record_success(domain)

    # ---- Phase 1–8 per-page enrichment (all additive, all non-fatal) ----

    # Phase 2: freshness score from published date
    if _HAS_FRESHNESS:
        try:
            result.setdefault("published_date", None)
            result["freshness_score"] = _freshness(result.get("published_date"))
        except Exception:
            result.setdefault("freshness_score", 0.5)
    else:
        result.setdefault("freshness_score", 0.5)

    # Phase 3: continuous domain trust score
    if _HAS_TRUST:
        try:
            result["domain_trust_score"] = _trust_score(url)
        except Exception:
            result.setdefault("domain_trust_score", 0.5)
    else:
        result.setdefault("domain_trust_score", 0.5)

    # Phase 5: structured review extraction
    if _HAS_EXTRACTOR:
        try:
            result["structured_review"] = _extract_structure(result.get("content", ""), url)
        except Exception:
            result.setdefault("structured_review", None)

    # source_type defaults (overwritten by fetch_all_reviews when known)
    result.setdefault("source_type", "gemini_grounding")
    result.setdefault("retrieval_confidence", 0.80)

    cache.set("review_page", url, result)
    return result


def _extract_content(html: str, url: str) -> dict | None:
    from bs4 import BeautifulSoup  # lazy: only needed when actually parsing HTML
    soup = BeautifulSoup(html, "html.parser")

    # Phase 2: extract publish date from HTML metadata BEFORE stripping tags
    pub_date: str | None = None
    if _HAS_FRESHNESS:
        try:
            pub_date = _extract_date(html, url)
        except Exception:
            pass

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
        "published_date": pub_date,   # Phase 2: may be None
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

    Phase 1 enhancement: additional expert editorial + news candidates are merged
    when Serper is configured.  Gemini grounding behavior is unchanged.
    """
    from source_filter import filter_review_urls

    gemini_urls = find_review_urls_via_gemini(query, limit=limit)
    gemini_fallback_used = False

    # Serper fallback if Gemini returned nothing
    if not gemini_urls:
        print("[reviews] Gemini returned 0 URLs, trying Serper fallback...")
        gemini_urls = _find_review_urls_via_serper(query, limit=limit)
        gemini_fallback_used = True

    # Phase 1: augment with expert editorial + news candidates (additive only)
    # Maps url → source metadata so we can tag results after scraping.
    url_metadata: dict[str, dict] = {}
    for u in gemini_urls:
        url_metadata[u] = {
            "source_type": "serper_fallback" if gemini_fallback_used else "gemini_grounding",
            "discovered_from": "serper_fallback" if gemini_fallback_used else "gemini",
            "retrieval_confidence": 0.65 if gemini_fallback_used else 0.90,
        }

    if _HAS_CANDIDATES:
        try:
            extra = _retrieve_candidates(
                query, gemini_urls=[], extra_limit=limit // 2,
                region=detect_region(query),
            )
            for cand in extra:
                if cand.url not in url_metadata:
                    url_metadata[cand.url] = {
                        "source_type": cand.source_type,
                        "discovered_from": cand.discovered_from,
                        "retrieval_confidence": cand.retrieval_confidence,
                    }
                    gemini_urls.append(cand.url)
        except Exception as e:
            print(f"[reviews] Phase 1 candidate augmentation failed (non-fatal): {e}")

    if not gemini_urls:
        print("[reviews] no review URLs found from any source")
        return []

    # Filter affiliate junk — conservative, whitelist always wins
    urls = filter_review_urls(gemini_urls)
    if not urls:
        print("[reviews] all URLs filtered as junk — check source_filter.py whitelist")
        return []

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[scrape] {i}/{len(urls)}: {url}")
        page = fetch_review_page(url)
        if page:
            # Phase 1: tag with discovery metadata (not cached — context-specific)
            meta = url_metadata.get(url, {})
            page["source_type"] = meta.get("source_type", page.get("source_type", "gemini_grounding"))
            page["discovered_from"] = meta.get("discovered_from", "gemini")
            page["retrieval_confidence"] = meta.get("retrieval_confidence", page.get("retrieval_confidence", 0.80))

            # Phase 8: compute rank score now that retrieval_confidence is known
            if _HAS_RANKER:
                try:
                    page["review_rank_score"] = _rank_score(
                        trust_score=page.get("domain_trust_score", 0.5),
                        freshness_score=page.get("freshness_score", 0.5),
                        content=page.get("content", ""),
                        retrieval_confidence=page["retrieval_confidence"],
                    )
                except Exception:
                    pass

            results.append(page)
        time.sleep(delay)
    print(f"[scrape] {len(results)}/{len(urls)} succeeded")

    # Phase 4: YouTube intelligence — supplementary evidence, appended after web reviews
    if _HAS_YOUTUBE:
        try:
            yt_reviews = _fetch_youtube(query)
            for yt in yt_reviews:
                # Enrich YouTube results with freshness/trust defaults
                yt.setdefault("freshness_score", 0.80)  # transcripts are always current
                yt.setdefault("domain_trust_score", yt.get("trust_score", 0.55))
                yt.setdefault("review_rank_score", 0.60 if yt.get("channel_is_trusted") else 0.45)
                yt.setdefault("structured_review", None)
                yt.setdefault("authority_tier", "good" if yt.get("channel_is_trusted") else "unknown")
                # Remap 'transcript_snippet' → 'content' so downstream code works unchanged
                if "content" not in yt and "transcript_snippet" in yt:
                    yt["content"] = yt["transcript_snippet"]
            results.extend(yt_reviews)
            if yt_reviews:
                print(f"[youtube] appended {len(yt_reviews)} YouTube review(s)")
        except Exception as e:
            print(f"[reviews] YouTube fetch failed (non-fatal): {e}")

    # Phase 7: contradiction detection — stored on every result dict so the caller
    # (and analyzer) can access it from the first element.
    if _HAS_CONTRADICTION and len(results) >= 2:
        try:
            conflicts = _detect_conflicts(results)
            for r in results:
                r["conflict_signals"] = conflicts
        except Exception as e:
            print(f"[reviews] contradiction detection failed (non-fatal): {e}")

    return results