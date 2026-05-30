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


# ---- Category-aware review site lists ----

def _get_category_sites(q_lower: str, region: str) -> list[str]:
    """Return authoritative review sites for this query's category and region."""
    if region == "india":
        if any(t in q_lower for t in ["skincare", "skin care", "facewash", "face wash",
                                        "moisturizer", "serum", "sunscreen", "toner", "makeup",
                                        "beauty", "foundation", "lipstick", "cleanser", "bodylotion",
                                        "body lotion", "face cream", "eye cream", "vitamin c"]):
            return ["nykaa.com", "purplle.com", "bebeautiful.in", "incidecoder.com", "cosdna.com"]
        if any(t in q_lower for t in ["phone", "smartphone", "mobile"]):
            return ["smartprix.com", "91mobiles.com", "gsmarena.com", "gadgets360.com"]
        if any(t in q_lower for t in ["laptop", "notebook", "ultrabook"]):
            return ["digit.in", "91mobiles.com", "gadgets360.com", "smartprix.com", "notebookcheck.net"]
        if any(t in q_lower for t in ["monitor", "display screen"]):
            return ["digit.in", "gadgets360.com", "smartprix.com", "rtings.com"]
        if any(t in q_lower for t in ["tv", "television", "oled", "qled", "projector"]):
            return ["smartprix.com", "digit.in", "gadgets360.com", "rtings.com"]
        if any(t in q_lower for t in ["ac", "air conditioner", "refrigerator", "fridge",
                                        "washing machine", "dishwasher", "appliance", "geyser", "water heater"]):
            return ["smartprix.com", "compare.in", "gadgets360.com", "indianexpress.com", "livemint.com"]
        if any(t in q_lower for t in ["headphone", "earbud", "earpod", "earphone", "speaker", "soundbar", "audio"]):
            return ["smartprix.com", "91mobiles.com", "soundguys.com", "gadgets360.com", "rtings.com"]
        if any(t in q_lower for t in ["keyboard", "mouse", "peripheral", "gaming"]):
            return ["digit.in", "gadgets360.com", "smartprix.com", "rtings.com"]
        if any(t in q_lower for t in ["watch", "wristwatch", "smartwatch", "fitness band", "fitness tracker"]):
            return ["91mobiles.com", "smartprix.com", "gadgets360.com", "dcrainmaker.com"]
        if any(t in q_lower for t in ["camera", "dslr", "mirrorless", "lens"]):
            return ["digit.in", "dpreview.com", "gadgets360.com", "imaging-resource.com"]
        if any(t in q_lower for t in ["kitchen", "cookware", "pressure cooker", "pan", "pot",
                                        "mixer", "blender", "juicer", "oven", "microwave", "air fryer"]):
            return ["gadgets360.com", "indianexpress.com", "seriouseats.com", "wirecutter.com"]
        if any(t in q_lower for t in ["fitness", "gym", "treadmill", "cycle", "workout", "exercise"]):
            return ["gadgets360.com", "dcrainmaker.com", "healthshots.com", "t3.com"]
        if any(t in q_lower for t in ["mattress", "bed", "pillow", "blanket", "bedding"]):
            return ["sleepopolis.com", "sleepfoundation.org", "theindusparent.com"]
        if any(t in q_lower for t in ["shoe", "footwear", "sneaker", "boot", "sandal"]):
            return ["runrepeat.com", "runnersworld.com", "ndtv.com"]
        if any(t in q_lower for t in ["bag", "backpack", "luggage", "suitcase"]):
            return ["wirecutter.com", "indianexpress.com", "gadgets360.com"]
        if any(t in q_lower for t in ["vacuum", "robot vacuum", "air purifier"]):
            return ["wirecutter.com", "rtings.com", "gadgets360.com"]
        if any(t in q_lower for t in ["supplement", "protein", "vitamin", "nutrition", "whey"]):
            return ["examine.com", "healthshots.com", "thehealthsite.com"]
        return ["smartprix.com", "91mobiles.com", "gadgets360.com", "digit.in", "indianexpress.com"]

    elif region == "uk":
        if any(t in q_lower for t in ["skincare", "skin care", "facewash", "beauty", "makeup", "serum", "sunscreen"]):
            return ["lookfantastic.com", "beautybay.com", "incidecoder.com", "allure.com", "byrdie.com"]
        if any(t in q_lower for t in ["phone", "smartphone"]):
            return ["techradar.com", "trustedreviews.com", "gsmarena.com", "expertreviews.co.uk"]
        if any(t in q_lower for t in ["laptop", "notebook"]):
            return ["techradar.com", "trustedreviews.com", "notebookcheck.net", "expertreviews.co.uk"]
        if any(t in q_lower for t in ["headphone", "earbud", "earphone", "speaker", "audio"]):
            return ["whathifi.com", "techradar.com", "rtings.com", "soundguys.com"]
        if any(t in q_lower for t in ["tv", "television"]):
            return ["rtings.com", "whathifi.com", "techradar.com", "trustedreviews.com"]
        if any(t in q_lower for t in ["mattress", "bed", "pillow", "blanket", "bedding"]):
            return ["which.co.uk", "goodhousekeeping.com", "sleepopolis.com"]
        if any(t in q_lower for t in ["kitchen", "cookware", "appliance", "air fryer", "coffee"]):
            return ["which.co.uk", "goodhousekeeping.com", "bbcgoodfood.com", "seriouseats.com"]
        if any(t in q_lower for t in ["fitness", "gym", "running", "cycling", "smartwatch"]):
            return ["dcrainmaker.com", "techradar.com", "wareable.com", "runnersworld.com"]
        return ["which.co.uk", "techradar.com", "trustedreviews.com", "expertreviews.co.uk", "whathifi.com"]

    elif region == "australia":
        return ["choice.com.au", "finder.com.au", "techradar.com", "rtings.com", "gsmarena.com"]

    elif region == "canada":
        return ["techradar.com", "rtings.com", "notebookcheck.net", "pcmag.com", "cnet.com"]

    else:  # global / US
        if any(t in q_lower for t in ["skincare", "skin care", "facewash", "face wash",
                                        "moisturizer", "serum", "sunscreen", "toner", "makeup",
                                        "beauty", "foundation", "lipstick", "cleanser"]):
            return ["incidecoder.com", "cosdna.com", "allure.com", "byrdie.com", "paulaschoice.com"]
        if any(t in q_lower for t in ["headphone", "earbud", "earphone", "speaker", "soundbar", "audio", "dac", "amp"]):
            return ["rtings.com", "soundguys.com", "headphonesaddict.com", "stereophile.com", "whathifi.com"]
        if any(t in q_lower for t in ["tv", "television", "oled", "qled"]):
            return ["rtings.com", "displayspecifications.com", "cnet.com", "wirecutter.com"]
        if any(t in q_lower for t in ["monitor", "display"]):
            return ["rtings.com", "displayspecifications.com", "notebookcheck.net", "tftcentral.co.uk"]
        if any(t in q_lower for t in ["phone", "smartphone", "mobile"]):
            return ["gsmarena.com", "rtings.com", "notebookcheck.net", "techradar.com"]
        if any(t in q_lower for t in ["laptop", "notebook"]):
            return ["notebookcheck.net", "rtings.com", "laptopmag.com", "pcmag.com", "wirecutter.com"]
        if any(t in q_lower for t in ["camera", "dslr", "mirrorless", "lens"]):
            return ["dpreview.com", "imaging-resource.com", "cameralabs.com", "photographylife.com"]
        if any(t in q_lower for t in ["keyboard", "mechanical keyboard"]):
            return ["rtings.com", "switchandclick.com", "deskthority.net", "keebtalk.com"]
        if any(t in q_lower for t in ["mouse", "trackball"]):
            return ["rtings.com", "techradar.com", "pcmag.com"]
        if any(t in q_lower for t in ["kitchen", "cookware", "knife", "pan", "pot", "mixer",
                                        "blender", "coffee", "espresso", "oven", "microwave", "air fryer"]):
            return ["seriouseats.com", "wirecutter.com", "cooksillustrated.com", "seriouseats.com"]
        if any(t in q_lower for t in ["fitness", "gym", "treadmill", "cycle", "rowing", "workout",
                                        "running watch", "gps watch", "smart watch"]):
            return ["dcrainmaker.com", "t3.com", "runnersworld.com", "wareable.com"]
        if any(t in q_lower for t in ["mattress", "bed", "pillow", "blanket", "bedding", "sleep"]):
            return ["sleepopolis.com", "sleepfoundation.org", "goodhousekeeping.com", "wirecutter.com"]
        if any(t in q_lower for t in ["shoe", "footwear", "sneaker", "running shoe", "hiking boot"]):
            return ["runrepeat.com", "runnersworld.com", "cleverhiker.com", "wirecutter.com"]
        if any(t in q_lower for t in ["bag", "backpack", "luggage", "suitcase", "carry-on"]):
            return ["wirecutter.com", "outdoorgearlab.com", "cleverhiker.com"]
        if any(t in q_lower for t in ["vacuum", "robot vacuum", "air purifier"]):
            return ["wirecutter.com", "rtings.com", "consumerreports.org"]
        if any(t in q_lower for t in ["gaming", "game", "console", "xbox", "playstation", "nintendo"]):
            return ["ign.com", "eurogamer.net", "pcmag.com", "techradar.com"]
        if any(t in q_lower for t in ["bike", "bicycle", "cycling", "mtb", "road bike"]):
            return ["bikeradar.com", "bikeperfect.com", "cyclingnews.com"]
        if any(t in q_lower for t in ["watch", "wristwatch", "smartwatch"]):
            return ["rtings.com", "wareable.com", "dcrainmaker.com", "techradar.com"]
        if any(t in q_lower for t in ["supplement", "protein", "vitamin", "nutrition", "whey"]):
            return ["examine.com", "labdoor.com", "consumerlab.com", "healthline.com"]
        if any(t in q_lower for t in ["baby", "toddler", "infant", "stroller", "diaper"]):
            return ["babygearlab.com", "whattoexpect.com", "babylist.com"]
        if any(t in q_lower for t in ["pet", "dog", "cat", "fish", "bird", "pet food"]):
            return ["dogfoodadvisor.com", "petmd.com", "thesprucepets.com"]
        return ["wirecutter.com", "rtings.com", "cnet.com", "pcmag.com", "techradar.com"]


# ---- find review URLs ----

def find_review_urls_via_gemini(query: str, limit: int = 10) -> list[str]:
    """Use Gemini grounding to find non-Reddit review/article URLs.
    Region-aware: prioritizes regional sources if currency hints detected."""
    if not GEMINI_API_KEY:
        return []

    cache_key = f"reviews|{query}|{limit}"
    cached = cache.get("review_urls", cache_key)
    if cached is not None:
        print(f"[reviews] cache hit for: {query}")
        return cached

    # Detect region from query (₹/Rs = India, £ = UK, € = Europe, etc.)
    from reddit_fetch import detect_region
    region = detect_region(query)
    region_instruction = ""
    q_lower = query.lower()

    if region == "india":
        category_sites = _get_category_sites(q_lower, "india")
        sites_str = ", ".join(category_sites)
        region_instruction = (
            f"\n\nCRITICAL: This is an INDIAN market query (₹/Rs currency). "
            f"You MUST prioritize these category-relevant Indian/authoritative sites: {sites_str}. "
            f"Indian sites cover India-available models with Indian prices. "
            f"DO NOT return US-only sources unless they explicitly review Indian-market products."
        )
    elif region == "uk":
        category_sites = _get_category_sites(q_lower, "uk")
        sites_str = ", ".join(category_sites)
        region_instruction = (
            f"\n\nCRITICAL: This is a UK market query (£ currency). Prioritize: {sites_str}. "
            f"Avoid US-only sources unless they cover UK-available models."
        )
    elif region == "europe":
        region_instruction = (
            f"\n\nCRITICAL: This is a European market query (€ currency). Prioritize European tech publications "
            f"covering EU-available models with EU prices and warranties."
        )
    elif region == "australia":
        category_sites = _get_category_sites(q_lower, "australia")
        sites_str = ", ".join(category_sites)
        region_instruction = (
            f"\n\nThis is an Australian market query (A$). Prioritize: {sites_str}."
        )
    elif region == "canada":
        category_sites = _get_category_sites(q_lower, "canada")
        sites_str = ", ".join(category_sites)
        region_instruction = (
            f"\n\nThis is a Canadian market query (C$). Prioritize: {sites_str}."
        )
    else:
        # Global: still give category-specific guidance
        category_sites = _get_category_sites(q_lower, "global")
        if category_sites:
            sites_str = ", ".join(category_sites)
            region_instruction = (
                f"\n\nFor this product category, prioritize the most authoritative sources: {sites_str}."
            )

    prompt = (
        f"Find the top {limit} review articles and buying guides for: {query}\n\n"
        f"Look at trusted review sites (like Wirecutter, RTINGS, Strategist, specialist blogs, "
        f"industry publications - whichever are most respected for this product category). "
        f"Do NOT include Reddit, YouTube, Instagram, or social media."
        f"{region_instruction}"
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
    Category-aware: uses _get_category_sites for all regions."""
    import google_search
    if not google_search.is_configured():
        return []

    from reddit_fetch import detect_region
    region = detect_region(query)
    q_lower = query.lower()
    sites_list = _get_category_sites(q_lower, region or "global")

    if sites_list:
        site_filter = " OR ".join(f"site:{s}" for s in sites_list[:5])
        search_query = f"{query} review {site_filter}"
    else:
        search_query = f"{query} best review buying guide"

    results = google_search.search(search_query, num=limit)
    urls = []
    for r in results:
        link = r.get("link", "")
        if not link or "reddit.com" in link:
            continue
        urls.append(link)
    print(f"[reviews] serper fallback ({region or 'global'}): {len(urls)} review URLs")
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