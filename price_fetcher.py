"""
Real price fetcher for Shopping Research Agent v6.

Fetches actual current prices from Amazon and Flipkart (India) or Amazon
and Best Buy (USA) using the Serper API's search endpoints.

Usage:
    from price_fetcher import fetch_prices
    results = fetch_prices(["Realme Buds Air 7", "Sony WF-1000XM5"], region="india")

Each product returns:
{
    "product_name": "...",
    "retailers": [
        {
            "name": "Amazon India",
            "price_inr": 2499,
            "mrp_inr": 3499,
            "discount_pct": 29,
            "url": "https://...",
            "in_stock": True,
            "rating": 4.2,
            "review_count": 8453,
            "image_url": "https://..."
        }
    ],
    "best_price": {"retailer": "Flipkart", "price_inr": 2349},
    "price_range": [2349, 2799],
    "currency": "INR",
    "fetched_at": "ISO timestamp"
}

Caching: 6 hours (prices change throughout the day).
Concurrency: ThreadPoolExecutor with 5 workers, each product is one task.
"""

import os
import re
import json
import time
import logging
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urlparse, urlencode, parse_qs, urlunparse

import cache

logger = logging.getLogger(__name__)

# ── Product Link Intelligence Engine (fail-safe import) ──────────────────────
try:
    from product_link_intel import run_link_intelligence, LINK_INTEL_ENABLED
    from product_canonicalizer import canonicalize_product as _canonicalize
    _HAS_LINK_INTEL = True
except ImportError:
    _HAS_LINK_INTEL = False
    LINK_INTEL_ENABLED = False

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
AMAZON_AFFILIATE_TAG = os.environ.get("AMAZON_AFFILIATE_TAG", "")

PRICE_CACHE_TTL = 6 * 60 * 60   # 6 hours
MAX_WORKERS = 2                  # Keep low — Serper free tier has strict rate limits
SERPER_CALL_DELAY = 0.6          # Seconds between Serper requests (global, thread-safe)
SERPER_MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-API-KEY": SERPER_API_KEY,
    "Content-Type": "application/json",
}

# Global rate-limiter: no more than one Serper request every SERPER_CALL_DELAY seconds
_serper_lock = threading.Lock()
_serper_last_call = 0.0


def _serper_throttle() -> None:
    """Block until enough time has passed since the last Serper call."""
    global _serper_last_call
    with _serper_lock:
        elapsed = time.time() - _serper_last_call
        if elapsed < SERPER_CALL_DELAY:
            time.sleep(SERPER_CALL_DELAY - elapsed)
        _serper_last_call = time.time()

# Override the default 7-day TTL in cache.py for price entries
_ORIGINAL_TTL = cache.CACHE_TTL_SECONDS


def _price_cache_get(key: str):
    """Get from cache, but only honour PRICE_CACHE_TTL (6 h) not the 7-day default."""
    import hashlib
    from pathlib import Path

    cache_type = "price"
    h = hashlib.sha256(f"{cache_type}::{key}".encode()).hexdigest()[:16]
    path = cache.CACHE_DIR / f"{cache_type}_{h}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry["timestamp"] > PRICE_CACHE_TTL:
            return None
        return entry["value"]
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass
        return None


def _price_cache_set(key: str, value) -> None:
    cache.set("price", key, value)


# ---------------------------------------------------------------------------
# Serper helpers
# ---------------------------------------------------------------------------

def _serper_google_search(query: str, num: int = 5) -> list[dict]:
    """Run a Google search via Serper, with throttling and 429 retry."""
    if not SERPER_API_KEY:
        return []
    for attempt in range(1, SERPER_MAX_RETRIES + 1):
        _serper_throttle()
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers=HEADERS,
                json={"q": query, "num": num},
                timeout=12,
            )
            if resp.status_code == 429:
                wait = 5 * attempt
                logger.warning("Serper Google 429 (attempt %d), sleeping %ds", attempt, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("organic", [])
        except requests.HTTPError:
            break
        except Exception as e:
            logger.warning("Serper Google search failed for '%s': %s", query, e)
            break
    return []


def _serper_shopping_search(query: str, num: int = 5) -> list[dict]:
    """Use Serper's Shopping endpoint, with throttling and 429 retry."""
    if not SERPER_API_KEY:
        return []
    for attempt in range(1, SERPER_MAX_RETRIES + 1):
        _serper_throttle()
        try:
            resp = requests.post(
                "https://google.serper.dev/shopping",
                headers=HEADERS,
                json={"q": query, "num": num},
                timeout=12,
            )
            if resp.status_code == 429:
                wait = 5 * attempt
                logger.warning("Serper Shopping 429 (attempt %d), sleeping %ds", attempt, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("shopping", [])
        except requests.HTTPError:
            break
        except Exception as e:
            logger.warning("Serper Shopping search failed for '%s': %s", query, e)
            break
    return []


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

def _parse_inr(text: str | None) -> int | None:
    """Extract an integer INR price from strings like '₹2,499', 'Rs. 2499', etc."""
    if not text:
        return None
    text = str(text)
    cleaned = re.sub(r"[^\d]", "", text)
    if cleaned:
        val = int(cleaned)
        # Sanity: ignore absurd values (< ₹50 or > ₹10 lakh)
        if 50 <= val <= 1_000_000:
            return val
    return None


def _parse_usd(text: str | None) -> int | None:
    """Extract integer USD price from strings like '$49.99', '49', etc."""
    if not text:
        return None
    text = str(text)
    # Remove $ and commas, keep digits and dot
    cleaned = re.sub(r"[^0-9.]", "", text)
    if cleaned:
        try:
            val = float(cleaned)
            if 1 <= val <= 100_000:
                return int(val)
        except ValueError:
            pass
    return None


def _apply_affiliate_tag(url: str) -> str:
    """Append Amazon affiliate tag if configured."""
    if not AMAZON_AFFILIATE_TAG or not url:
        return url
    if "amazon." not in url.lower():
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["tag"] = [AMAZON_AFFILIATE_TAG]
    new_qs = urlencode({k: v[0] for k, v in qs.items()})
    return urlunparse(parsed._replace(query=new_qs))


# ---------------------------------------------------------------------------
# Per-retailer fetchers
# ---------------------------------------------------------------------------

def _fetch_amazon_india(product_name: str) -> dict | None:
    """Search Amazon.in via Serper Shopping — collect top-5 candidates for intelligence."""
    query = f"{product_name} site:amazon.in"
    results = _serper_shopping_search(query, num=5)
    if not results:
        results = _serper_google_search(f"{product_name} amazon.in buy", num=5)

    candidates: list[dict] = []
    first_result: dict | None = None

    for r in results:
        url = r.get("link") or r.get("url") or ""
        if "amazon.in" not in url.lower():
            continue

        price_raw = r.get("price") or r.get("extracted_price")
        price = _parse_inr(str(price_raw)) if price_raw else None
        if not price:
            continue

        rating_raw = r.get("rating")
        review_count_raw = r.get("ratingCount") or r.get("reviews")

        entry = {
            "name": "Amazon India",
            "price_inr": price,
            "mrp_inr": None,
            "discount_pct": None,
            "url": _apply_affiliate_tag(url),
            "in_stock": True,
            "rating": float(rating_raw) if rating_raw else None,
            "review_count": int(re.sub(r"[^\d]", "", str(review_count_raw))) if review_count_raw else None,
            "image_url": r.get("imageUrl") or r.get("thumbnailUrl"),
            "title": r.get("title", ""),
        }
        candidates.append(entry)
        if first_result is None:
            first_result = entry

    if first_result:
        first_result["_candidates"] = candidates
    return first_result


def _fetch_flipkart(product_name: str) -> dict | None:
    """Search Flipkart via Serper Shopping — collect top-5 candidates."""
    query = f"{product_name} site:flipkart.com"
    results = _serper_shopping_search(query, num=5)
    if not results:
        results = _serper_google_search(f"{product_name} flipkart.com buy online", num=5)

    candidates: list[dict] = []
    first_result: dict | None = None

    for r in results:
        url = r.get("link") or r.get("url") or ""
        if "flipkart.com" not in url.lower():
            continue

        price_raw = r.get("price") or r.get("extracted_price")
        price = _parse_inr(str(price_raw)) if price_raw else None
        if not price:
            continue

        review_raw = r.get("ratingCount") or r.get("reviews")
        entry = {
            "name": "Flipkart",
            "price_inr": price,
            "mrp_inr": None,
            "discount_pct": None,
            "url": url,
            "in_stock": True,
            "rating": float(r["rating"]) if r.get("rating") else None,
            "review_count": int(re.sub(r"[^\d]", "", str(review_raw))) if review_raw else None,
            "image_url": r.get("imageUrl") or r.get("thumbnailUrl"),
            "title": r.get("title", ""),
        }
        candidates.append(entry)
        if first_result is None:
            first_result = entry

    if first_result:
        first_result["_candidates"] = candidates
    return first_result


def _fetch_croma(product_name: str) -> dict | None:
    """Search Croma.com via Google Serper — collect top-5 candidates."""
    results = _serper_google_search(f"{product_name} site:croma.com buy price", num=5)

    candidates: list[dict] = []
    first_result: dict | None = None

    for r in results:
        url = r.get("link") or ""
        if "croma.com" not in url.lower():
            continue
        snippet = r.get("snippet", "")
        price = _parse_inr(snippet)
        if not price:
            continue
        entry = {
            "name": "Croma",
            "price_inr": price,
            "mrp_inr": None,
            "discount_pct": None,
            "url": url,
            "in_stock": True,
            "rating": None,
            "review_count": None,
            "image_url": None,
            "title": r.get("title", ""),
        }
        candidates.append(entry)
        if first_result is None:
            first_result = entry

    if first_result:
        first_result["_candidates"] = candidates
    return first_result


def _fetch_amazon_usa(product_name: str) -> dict | None:
    """Search Amazon.com via Serper Shopping — collect top-5 candidates."""
    query = f"{product_name} site:amazon.com"
    results = _serper_shopping_search(query, num=5)
    if not results:
        results = _serper_google_search(f"{product_name} amazon.com buy", num=5)

    candidates: list[dict] = []
    first_result: dict | None = None

    for r in results:
        url = r.get("link") or r.get("url") or ""
        if "amazon.com" not in url.lower():
            continue
        price_raw = r.get("price") or r.get("extracted_price")
        price = _parse_usd(str(price_raw)) if price_raw else None
        if not price:
            continue
        review_raw = r.get("ratingCount") or r.get("reviews")
        entry = {
            "name": "Amazon US",
            "price_usd": price,
            "url": _apply_affiliate_tag(url),
            "in_stock": True,
            "rating": float(r["rating"]) if r.get("rating") else None,
            "review_count": int(re.sub(r"[^\d]", "", str(review_raw))) if review_raw else None,
            "image_url": r.get("imageUrl") or r.get("thumbnailUrl"),
            "title": r.get("title", ""),
        }
        candidates.append(entry)
        if first_result is None:
            first_result = entry

    if first_result:
        first_result["_candidates"] = candidates
    return first_result


def _fetch_bestbuy(product_name: str) -> dict | None:
    """Search Best Buy via Serper Shopping — collect top-5 candidates."""
    query = f"{product_name} site:bestbuy.com"
    results = _serper_shopping_search(query, num=5)
    if not results:
        results = _serper_google_search(f"{product_name} bestbuy.com buy", num=5)

    candidates: list[dict] = []
    first_result: dict | None = None

    for r in results:
        url = r.get("link") or r.get("url") or ""
        if "bestbuy.com" not in url.lower():
            continue
        price_raw = r.get("price") or r.get("extracted_price")
        price = _parse_usd(str(price_raw)) if price_raw else None
        if not price:
            continue
        review_raw = r.get("ratingCount") or r.get("reviews")
        entry = {
            "name": "Best Buy",
            "price_usd": price,
            "url": url,
            "in_stock": True,
            "rating": float(r["rating"]) if r.get("rating") else None,
            "review_count": int(re.sub(r"[^\d]", "", str(review_raw))) if review_raw else None,
            "image_url": r.get("imageUrl") or r.get("thumbnailUrl"),
            "title": r.get("title", ""),
        }
        candidates.append(entry)
        if first_result is None:
            first_result = entry

    if first_result:
        first_result["_candidates"] = candidates
    return first_result


# ---------------------------------------------------------------------------
# Per-product orchestration
# ---------------------------------------------------------------------------

_RETAILER_FETCHERS = {
    "india": [_fetch_amazon_india, _fetch_flipkart, _fetch_croma],
    "usa": [_fetch_amazon_usa, _fetch_bestbuy],
}


def _fetch_one_product(product_name: str, region: str) -> dict:
    """
    Fetch prices for a single product from 2-3 retailers in parallel.
    Returns the structured price dict.
    """
    cache_key = f"{region}::{product_name.lower().strip()}"
    cached = _price_cache_get(cache_key)
    if cached is not None:
        return cached

    fetchers = _RETAILER_FETCHERS.get(region, [])
    if not fetchers:
        # Unsupported region — return search-URL fallback
        return _search_url_fallback(product_name, region)

    currency = "INR" if region == "india" else "USD"
    price_field = "price_inr" if region == "india" else "price_usd"

    retailers: list[dict] = []

    # Fetch retailers sequentially — all share the global Serper throttle so
    # concurrent workers would just block on the lock anyway.
    for fn in fetchers:
        try:
            result = fn(product_name)
            if result:
                retailers.append(result)
        except Exception as e:
            logger.warning("Retailer fetch failed for '%s': %s", product_name, e)

    if not retailers:
        result = _search_url_fallback(product_name, region)
        _price_cache_set(cache_key, result)
        return result

    # ── Product Link Intelligence (additive, fail-safe) ──────────────────────
    intel_data: dict | None = None
    if _HAS_LINK_INTEL and LINK_INTEL_ENABLED:
        try:
            canonical = _canonicalize(product_name)
            if canonical.parse_confidence >= 0.30:
                intel = run_link_intelligence(canonical, retailers, price_field)
                if intel:
                    intel_data = intel.to_dict()
                    # If intelligence found a better-matching result, promote it
                    # by reordering retailers so best match appears first.
                    if intel.best_candidate and intel.status == "confident":
                        best_url = intel.best_candidate.url
                        retailers.sort(
                            key=lambda r: 0 if r.get("url") == best_url else 1
                        )
                        # Tag each retailer with its match score
                        for r in retailers:
                            for cand in intel.all_candidates:
                                if r.get("url") == cand.url:
                                    r["match_score"] = round(cand.match_score, 3)
                                    break
        except Exception as _ie:
            logger.debug("Link intelligence failed (non-fatal): %s", _ie)

    # Determine best price — prefer intelligence-selected retailer when confident
    priced = [r for r in retailers if r.get(price_field)]
    if priced:
        if (
            intel_data
            and intel_data.get("status") == "confident"
            and intel_data.get("best_url")
        ):
            # Use the intelligence-selected retailer as "best"
            intel_best = next(
                (r for r in priced if r.get("url") == intel_data["best_url"]),
                min(priced, key=lambda r: r[price_field]),  # fallback to cheapest
            )
            best = intel_best
        else:
            best = min(priced, key=lambda r: r[price_field])
        prices = [r[price_field] for r in priced]
        price_range = [min(prices), max(prices)]
        best_price = {"retailer": best["name"], price_field: best[price_field]}
    else:
        best_price = None
        price_range = None

    # Compute discounts where we have both price and MRP
    for r in retailers:
        if r.get("price_inr") and r.get("mrp_inr") and r["mrp_inr"] > r["price_inr"]:
            r["discount_pct"] = round((r["mrp_inr"] - r["price_inr"]) / r["mrp_inr"] * 100)

    # Strip internal _candidates lists before storing (not needed downstream)
    for r in retailers:
        r.pop("_candidates", None)

    output: dict = {
        "product_name": product_name,
        "retailers": retailers,
        "best_price": best_price,
        "price_range": price_range,
        "currency": currency,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }
    if intel_data:
        output["intelligence"] = intel_data

    _price_cache_set(cache_key, output)
    return output


def _search_url_fallback(product_name: str, region: str) -> dict:
    """When all retailer fetches fail, return generic search URLs."""
    encoded = quote_plus(product_name)
    if region == "india":
        retailers = [
            {"name": "Amazon India", "url": f"https://www.amazon.in/s?k={encoded}", "is_search": True},
            {"name": "Flipkart", "url": f"https://www.flipkart.com/search?q={encoded}", "is_search": True},
        ]
    elif region == "usa":
        retailers = [
            {"name": "Amazon US", "url": f"https://www.amazon.com/s?k={encoded}", "is_search": True},
            {"name": "Best Buy", "url": f"https://www.bestbuy.com/site/searchpage.jsp?st={encoded}", "is_search": True},
        ]
    else:
        retailers = [
            {"name": "Google Shopping", "url": f"https://www.google.com/search?tbm=shop&q={encoded}", "is_search": True},
        ]
    return {
        "product_name": product_name,
        "retailers": retailers,
        "best_price": None,
        "price_range": None,
        "currency": "INR" if region == "india" else "USD",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "is_fallback": True,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_prices(product_names: list[str], region: str = "india") -> list[dict]:
    """
    Fetch real prices for multiple products in parallel (5 workers).

    Args:
        product_names: list of product name strings
        region: "india" | "usa" | others (fallback to search URLs)

    Returns:
        list of price dicts, one per product, in input order.
    """
    if not product_names:
        return []

    results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_one_product, name, region): i
            for i, name in enumerate(product_names)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error("Price fetch failed for index %d: %s", idx, e)
                results[idx] = _search_url_fallback(product_names[idx], region)

    return [results[i] for i in range(len(product_names))]
