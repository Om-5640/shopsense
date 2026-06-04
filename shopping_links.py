"""
Shopping links generator.

For each product, generates buy links from the best retailers for the user's region.
Supports Amazon Associates affiliate tags (set AMAZON_AFFILIATE_TAG in .env).

Strategy:
1. Determine region from query (₹/Rs → India, £ → UK, $ → US, etc.)
2. Pick region-appropriate retailers (Amazon.in + Flipkart for India, etc.)
3. Build search URL for each retailer with affiliate tag if configured
4. Optionally validate via Serper search for direct product URLs (cached)

Design philosophy:
- Always return SOMETHING - if Serper fails, fall back to retailer search URLs
- Affiliate tag is opt-in via env var, never fails the system if missing
- Cache aggressively - same product across runs uses cached links

Bugs fixed:
  Bug 1: URL validation now checks product identity (title + snippet + URL tokens) before
         accepting a Serper result — prevents returning accessories/cases for the wrong product.
  Bug 2: Category matching uses `in` instead of `startswith` — handles "electronics/skincare".
  Bug 4: print() → logger.warning().

Optimisations added:
  O1: Serper lookups are now parallel (ThreadPoolExecutor) — 3 serial waits → 1 parallel wait.
  O3: Cache key uses a normalised product name — "WF-C700N" and "wf c700n" share a cache entry.
"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus
from dotenv import load_dotenv

import cache
import google_search
from reddit_fetch import detect_region as _detect_region_fn

load_dotenv()

logger = logging.getLogger(__name__)

AMAZON_AFFILIATE_TAG = os.environ.get("AMAZON_AFFILIATE_TAG", "")


# ── Retailer configs ──────────────────────────────────────────────────────────

INDIA_BEAUTY_RETAILERS = [
    {"name": "Nykaa",         "domain": "nykaa.com",        "search": "https://www.nykaa.com/search/result/?q={query}"},
    {"name": "Purplle",       "domain": "purplle.com",       "search": "https://www.purplle.com/search?q={query}"},
    {"name": "Amazon India",  "domain": "amazon.in",         "search": "https://www.amazon.in/s?k={query}",   "affiliate_param": "tag"},
    {"name": "Tira",          "domain": "tirabeauty.com",    "search": "https://www.tirabeauty.com/search?q={query}"},
]

BEAUTY_CATEGORY_PREFIXES = ("skincare", "beauty", "personal-care", "haircare", "makeup", "cosmetics")

REGION_RETAILERS = {
    "india": [
        {"name": "Amazon India", "domain": "amazon.in",        "search": "https://www.amazon.in/s?k={query}",                              "affiliate_param": "tag"},
        {"name": "Flipkart",     "domain": "flipkart.com",     "search": "https://www.flipkart.com/search?q={query}"},
        {"name": "Croma",        "domain": "croma.com",        "search": "https://www.croma.com/search/?text={query}"},
    ],
    "uk": [
        {"name": "Amazon UK",    "domain": "amazon.co.uk",     "search": "https://www.amazon.co.uk/s?k={query}",                           "affiliate_param": "tag"},
        {"name": "Argos",        "domain": "argos.co.uk",      "search": "https://www.argos.co.uk/search/{query}"},
        {"name": "John Lewis",   "domain": "johnlewis.com",    "search": "https://www.johnlewis.com/search?search-term={query}"},
    ],
    "europe": [
        {"name": "Amazon DE",    "domain": "amazon.de",        "search": "https://www.amazon.de/s?k={query}",                              "affiliate_param": "tag"},
    ],
    "australia": [
        {"name": "Amazon AU",    "domain": "amazon.com.au",    "search": "https://www.amazon.com.au/s?k={query}",                          "affiliate_param": "tag"},
        {"name": "JB Hi-Fi",     "domain": "jbhifi.com.au",    "search": "https://www.jbhifi.com.au/search?query={query}"},
    ],
    "canada": [
        {"name": "Amazon CA",    "domain": "amazon.ca",        "search": "https://www.amazon.ca/s?k={query}",                              "affiliate_param": "tag"},
        {"name": "Best Buy CA",  "domain": "bestbuy.ca",       "search": "https://www.bestbuy.ca/en-ca/search?search={query}"},
    ],
    "japan": [
        {"name": "Amazon JP",    "domain": "amazon.co.jp",     "search": "https://www.amazon.co.jp/s?k={query}",                           "affiliate_param": "tag"},
    ],
    "usa": [
        {"name": "Amazon",       "domain": "amazon.com",       "search": "https://www.amazon.com/s?k={query}",                             "affiliate_param": "tag"},
        {"name": "Best Buy",     "domain": "bestbuy.com",      "search": "https://www.bestbuy.com/site/searchpage.jsp?st={query}"},
        {"name": "Target",       "domain": "target.com",       "search": "https://www.target.com/s?searchTerm={query}"},
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_region(query: str) -> str:
    return _detect_region_fn(query) or "usa"


def _normalize_product_name(name: str) -> str:
    """
    Canonical form used as cache key (O3 fix).
    'Sony WF-C700N' and 'sony wf c700n' map to the same key.
    """
    n = name.lower().strip()
    n = re.sub(r"[\s\-/]+", " ", n)   # normalise separators → space
    n = re.sub(r"[^\w\s]", "", n)     # strip remaining punctuation
    return n.strip()


def _add_affiliate_tag(url: str, retailer: dict) -> str:
    """Append Amazon affiliate tag to URL if configured."""
    if not AMAZON_AFFILIATE_TAG:
        return url
    param_name = retailer.get("affiliate_param")
    if not param_name or "amazon" not in retailer.get("domain", ""):
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{param_name}={AMAZON_AFFILIATE_TAG}"


def _retailer_search_url(retailer: dict, product_name: str) -> str:
    """Build a retailer search URL with affiliate tag if applicable."""
    return _add_affiliate_tag(
        retailer["search"].format(query=quote_plus(product_name)),
        retailer,
    )


# ── Bug 1 fix: product-identity validation ────────────────────────────────────

_STOPWORDS = frozenset({
    "best", "for", "the", "and", "with", "buy", "new", "review",
    "edition", "series", "gen", "pro", "plus", "max", "mini", "ultra",
})


def _product_tokens(product_name: str) -> list[str]:
    """
    Extract the most distinctive tokens from a product name.
    Model identifiers (contain digits: 'WF-C700N', 'XM5') are prioritised
    since they are unique to a specific product, unlike brand/category words.
    """
    raw = re.split(r"[\s,/]+", product_name.lower())
    raw = [t.strip("-").strip() for t in raw if t.strip("-")]

    model_tokens = [t for t in raw if any(c.isdigit() for c in t) and len(t) >= 2]
    word_tokens  = [t for t in raw if t.isalpha() and len(t) >= 4 and t not in _STOPWORDS]

    # Brand + secondary word + model identifiers → most selective signal
    result = word_tokens[:2] + model_tokens
    return list(dict.fromkeys(result))[:5]   # deduplicated, max 5


def _title_url_match(link: str, title: str, snippet: str, product_name: str) -> bool:
    """
    Return True if a Serper result plausibly matches the exact product (Bug 1 fix).

    Collapses hyphens/spaces before comparison so 'WF-C700N', 'wfc700n', 'wf c700n'
    all match. Accepts the URL when at least half of the distinctive product tokens
    appear across the URL + title + snippet.
    """
    tokens = _product_tokens(product_name)
    if not tokens:
        return True  # unvalidatable name — give benefit of doubt

    haystack = f"{link} {title} {snippet}".lower()
    # Normalise separators so 'WF-C700N' matches 'wfc700n' in a URL slug
    haystack_norm = re.sub(r"[-\s]+", "", haystack)

    hits = sum(
        1 for t in tokens
        if re.sub(r"[-\s]+", "", t) in haystack_norm
    )
    required = max(1, (len(tokens) + 1) // 2)
    return hits >= required


# ── Direct URL lookup (single retailer) ──────────────────────────────────────

def _find_direct_product_url(product_name: str, retailer: dict) -> str | None:
    """
    Use Serper to find a direct product-page URL (not a search-results page).
    Validates identity before accepting (Bug 1).
    Uses a normalised cache key (O3).
    Returns None on any failure — never raises.
    """
    if not google_search.is_configured():
        return None

    # O3: normalised key → cache hit for near-duplicate product names
    norm = _normalize_product_name(product_name)
    cache_key = f"product_url|{retailer['domain']}|{norm}"
    cached = cache.get("shopping_links", cache_key)
    if cached is not None:
        return cached or None   # "" means "searched, found nothing"

    try:
        results = google_search.search(
            f"site:{retailer['domain']} {product_name}", num=5
        )
        for r in results:
            link    = r.get("link", "")
            title   = r.get("title", "")
            snippet = r.get("snippet", "")

            if not link or retailer["domain"] not in link:
                continue
            if "/search" in link.lower():
                continue   # skip search-results pages

            # Bug 1 fix: validate that this URL is for the right product
            if not _title_url_match(link, title, snippet, product_name):
                logger.debug(
                    "[shopping] skipping URL (token mismatch) for %s: %s",
                    product_name, link,
                )
                continue

            url = _add_affiliate_tag(link, retailer)
            cache.set("shopping_links", cache_key, url)
            return url

    except Exception as exc:
        logger.warning(
            "[shopping] direct URL lookup failed for %s: %s",  # Bug 4 fix
            retailer["name"], exc,
        )

    cache.set("shopping_links", cache_key, "")
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def generate_links_for_product(
    product_name: str,
    query: str,
    use_serper: bool = False,
    category: str = "",
) -> list[dict]:
    """
    Generate buy links for a product.
    Returns list of {retailer, url, is_direct, is_affiliate}.

    use_serper=True  → parallel Serper calls for direct product pages (O1 fix).
    use_serper=False → instant retailer search URLs, no API calls.
    """
    region = _detect_region(query)

    # Bug 2 fix: `in` instead of `startswith` — handles "electronics/skincare"
    if region == "india" and category and any(
        p in category.lower() for p in BEAUTY_CATEGORY_PREFIXES
    ):
        retailers = INDIA_BEAUTY_RETAILERS
    else:
        retailers = REGION_RETAILERS.get(region, REGION_RETAILERS["usa"])

    # O1 fix: parallel Serper lookups instead of sequential
    direct_urls: dict[str, str | None] = {}
    if use_serper and google_search.is_configured():
        with ThreadPoolExecutor(max_workers=min(len(retailers), 4)) as pool:
            future_map = {
                pool.submit(_find_direct_product_url, product_name, r): r["name"]
                for r in retailers
            }
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    direct_urls[name] = future.result()
                except Exception:
                    direct_urls[name] = None

    links = []
    for retailer in retailers:
        direct = direct_urls.get(retailer["name"]) if use_serper else None
        url = direct or _retailer_search_url(retailer, product_name)
        links.append({
            "retailer":    retailer["name"],
            "url":         url,
            "is_direct":   bool(direct),
            "is_affiliate": bool(
                AMAZON_AFFILIATE_TAG
                and retailer.get("affiliate_param")
                and "amazon" in retailer.get("domain", "")
            ),
        })

    return links


def is_affiliate_configured() -> bool:
    return bool(AMAZON_AFFILIATE_TAG)
