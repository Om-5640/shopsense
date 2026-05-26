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
"""

import os
import re
from urllib.parse import quote_plus
from dotenv import load_dotenv

import cache
import google_search

load_dotenv()

AMAZON_AFFILIATE_TAG = os.environ.get("AMAZON_AFFILIATE_TAG", "")  # e.g. "yourname-20"


# Region → list of retailer configs in priority order
# Beauty-specific India retailers (used for skincare/personal-care categories)
INDIA_BEAUTY_RETAILERS = [
    {"name": "Nykaa", "domain": "nykaa.com", "search": "https://www.nykaa.com/search/result/?q={query}"},
    {"name": "Purplle", "domain": "purplle.com", "search": "https://www.purplle.com/search?q={query}"},
    {"name": "Amazon India", "domain": "amazon.in", "search": "https://www.amazon.in/s?k={query}", "affiliate_param": "tag"},
    {"name": "Tira", "domain": "tirabeauty.com", "search": "https://www.tirabeauty.com/search?q={query}"},
]

# Category prefixes that should use beauty retailers (India)
BEAUTY_CATEGORY_PREFIXES = ("skincare", "beauty", "personal-care", "haircare", "makeup", "cosmetics")


REGION_RETAILERS = {
    "india": [
        {"name": "Amazon India", "domain": "amazon.in", "search": "https://www.amazon.in/s?k={query}", "affiliate_param": "tag"},
        {"name": "Flipkart", "domain": "flipkart.com", "search": "https://www.flipkart.com/search?q={query}"},
        {"name": "Croma", "domain": "croma.com", "search": "https://www.croma.com/search/?text={query}"},
    ],
    "uk": [
        {"name": "Amazon UK", "domain": "amazon.co.uk", "search": "https://www.amazon.co.uk/s?k={query}", "affiliate_param": "tag"},
        {"name": "Argos", "domain": "argos.co.uk", "search": "https://www.argos.co.uk/search/{query}"},
        {"name": "John Lewis", "domain": "johnlewis.com", "search": "https://www.johnlewis.com/search?search-term={query}"},
    ],
    "europe": [
        {"name": "Amazon DE", "domain": "amazon.de", "search": "https://www.amazon.de/s?k={query}", "affiliate_param": "tag"},
    ],
    "australia": [
        {"name": "Amazon AU", "domain": "amazon.com.au", "search": "https://www.amazon.com.au/s?k={query}", "affiliate_param": "tag"},
        {"name": "JB Hi-Fi", "domain": "jbhifi.com.au", "search": "https://www.jbhifi.com.au/search?query={query}"},
    ],
    "canada": [
        {"name": "Amazon CA", "domain": "amazon.ca", "search": "https://www.amazon.ca/s?k={query}", "affiliate_param": "tag"},
        {"name": "Best Buy CA", "domain": "bestbuy.ca", "search": "https://www.bestbuy.ca/en-ca/search?search={query}"},
    ],
    "japan": [
        {"name": "Amazon JP", "domain": "amazon.co.jp", "search": "https://www.amazon.co.jp/s?k={query}", "affiliate_param": "tag"},
    ],
    "usa": [  # default
        {"name": "Amazon", "domain": "amazon.com", "search": "https://www.amazon.com/s?k={query}", "affiliate_param": "tag"},
        {"name": "Best Buy", "domain": "bestbuy.com", "search": "https://www.bestbuy.com/site/searchpage.jsp?st={query}"},
        {"name": "Target", "domain": "target.com", "search": "https://www.target.com/s?searchTerm={query}"},
    ],
}


def _detect_region(query: str) -> str:
    """Reuse the same region detection as reddit_fetch."""
    from reddit_fetch import detect_region
    return detect_region(query) or "usa"


def _add_affiliate_tag(url: str, retailer: dict) -> str:
    """Append affiliate tag to URL if configured and supported by retailer."""
    if not AMAZON_AFFILIATE_TAG:
        return url
    param_name = retailer.get("affiliate_param")
    if not param_name or "amazon" not in retailer.get("domain", ""):
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{param_name}={AMAZON_AFFILIATE_TAG}"


def _retailer_search_url(retailer: dict, product_name: str) -> str:
    """Build a search URL for this retailer, with affiliate if applicable."""
    template = retailer["search"]
    url = template.format(query=quote_plus(product_name))
    return _add_affiliate_tag(url, retailer)


def _find_direct_product_url(product_name: str, retailer: dict) -> str | None:
    """
    Use Serper to find a direct product page URL (better than search results page).
    Returns None gracefully on any failure. Cached.
    """
    if not google_search.is_configured():
        return None

    cache_key = f"product_url|{retailer['domain']}|{product_name.lower()}"
    cached = cache.get("shopping_links", cache_key)
    if cached is not None:
        return cached or None  # cached "no result" returns None

    try:
        # Search for direct product page on this specific retailer
        query = f"site:{retailer['domain']} {product_name}"
        results = google_search.search(query, num=3)
        for r in results:
            link = r.get("link", "")
            if retailer["domain"] in link and "/search" not in link.lower():
                # Direct product page, not a search result page
                url = _add_affiliate_tag(link, retailer)
                cache.set("shopping_links", cache_key, url)
                return url
    except Exception as e:
        print(f"   [shopping] direct URL lookup failed for {retailer['name']}: {e}")

    cache.set("shopping_links", cache_key, "")  # cache the "not found" too
    return None


def generate_links_for_product(product_name: str, query: str, use_serper: bool = False,
                               category: str = "") -> list[dict]:
    """
    Generate buy links for a product.
    Returns list of {retailer_name, url, is_direct, is_affiliate}.

    use_serper=True attempts direct product URLs (1 Serper call per retailer).
    use_serper=False just returns retailer search URLs (free, instant).
    Category-aware: India + beauty category → uses Nykaa/Purplle instead of Croma.
    """
    region = _detect_region(query)
    # Use beauty retailers for India beauty/skincare categories
    if region == "india" and category and any(
        category.lower().startswith(p) for p in BEAUTY_CATEGORY_PREFIXES
    ):
        retailers = INDIA_BEAUTY_RETAILERS
    else:
        retailers = REGION_RETAILERS.get(region, REGION_RETAILERS["usa"])

    links = []
    for retailer in retailers:
        url = None
        is_direct = False

        if use_serper:
            url = _find_direct_product_url(product_name, retailer)
            if url:
                is_direct = True

        if not url:
            url = _retailer_search_url(retailer, product_name)

        is_affiliate = bool(
            AMAZON_AFFILIATE_TAG
            and retailer.get("affiliate_param")
            and "amazon" in retailer.get("domain", "")
        )

        links.append({
            "retailer": retailer["name"],
            "url": url,
            "is_direct": is_direct,
            "is_affiliate": is_affiliate,
        })

    return links


def is_affiliate_configured() -> bool:
    return bool(AMAZON_AFFILIATE_TAG)