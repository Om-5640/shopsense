"""
Source authority and affiliate filtering.

Philosophy:
- Conservative: when in doubt, KEEP the site. A false negative (missing good content)
  is worse than a false positive (including mediocre content).
- Whitelist always wins: if a domain is on the trusted list, it NEVER gets filtered
  regardless of what the pattern matcher says.
- Only block sites that are unambiguously affiliate/SEO junk with zero editorial value.

Outputs:
  should_skip(url)                   → (bool, reason_str)
  get_authority_tier(url)            → "trusted" / "good" / "unknown" / "low"
  get_authority_score(url, category) → int 0-100 (O1: numeric authority)
  get_source_type(url)               → "editorial" / "community" / "commerce" / "blog" / "unknown"
  filter_review_urls(urls)           → list[str]

Bug fixes applied:
  Bug 1: International TLD variants (wired.co.uk → trusted) via brand-name matching
  Bug 2: Junk patterns require word-boundary match to avoid false positives
  Bug 3: Path-based inspection downgrades known affiliate paths on trusted domains
  Bug 4: medium.com / substack.com moved to "unknown" (not "good") authority
  O3:    reddit.com source_type="community", not an editorial authority tier
  O4:    print() → logger
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── Whitelist: these NEVER get filtered ──────────────────────────────────────
# Keep adding to this freely. When in doubt, add here.

TRUSTED_DOMAINS: frozenset[str] = frozenset({
    # Global tech/product review authorities
    "wirecutter.com", "nytimes.com",
    "rtings.com",
    "thestrategist.com", "nymag.com",
    "techradar.com",
    "cnet.com",
    "tomsguide.com",
    "pcmag.com",
    "theverge.com",
    "engadget.com",
    "wired.com",
    "arstechnica.com",
    "consumerreports.org",
    "goodhousekeeping.com",
    "forbes.com",
    "businessinsider.com",
    "wsj.com",
    "bloomberg.com",
    # Bedding / home
    "sleepfoundation.org",
    "mattressclarity.com",
    "sleepopolis.com",
    # Audio / headphones
    "soundguys.com",
    "headfonics.com",
    "whathifi.com",
    "headphonesaddict.com",
    # Mobile / gadgets (India)
    "91mobiles.com",
    "smartprix.com",
    "gadgets360.com",
    "ndtv.com",
    "digit.in",
    "indianexpress.com",
    "livemint.com",
    "techpp.com",
    # Mobile / gadgets (Global)
    "gsmarena.com",
    "anandtech.com",
    "notebookcheck.net",
    "dxomark.com",
    # UK / Europe
    "which.co.uk",
    "trustedreviews.co.uk",
    "expertreviews.co.uk",
    # Fitness / running
    "runnerworld.com",
    "runnersworld.com",
    "roadrunnersports.com",
    # Skincare / beauty
    "allure.com",
    "byrdie.com",
    "cosmopolitan.com",
    # General shopping guides from trusted publishers
    "sfgate.com",
    "today.com",
    "health.com",
    "menshealth.com",
    "womenshealthmag.com",
})

# Bug 4 fix: medium.com / substack.com removed — mixed quality, not authoritative.
# O3 fix:   reddit.com removed — community evidence, not editorial.
# These are handled separately in get_source_type() and get_authority_score().
GOOD_DOMAINS: frozenset[str] = frozenset({
    "amazon.com",   # reviews section is useful
    "amazon.in",
    "amazon.co.uk",
    "bestbuy.com",  # review aggregation
    "flipkart.com", # reviews section India
})

# Domains that are community-sourced, not editorial (O3 fix)
_COMMUNITY_DOMAINS: frozenset[str] = frozenset({
    "reddit.com", "quora.com",
})

# Domains with mixed/blog-quality content — treated as "unknown", not "good"
_BLOG_DOMAINS: frozenset[str] = frozenset({
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
})


# ── Bug 1 fix: Brand-name authority families (handles wired.co.uk, techradar.com.au) ─

# Compound TLDs that appear before the brand name in international domains
_COMPOUND_TLDS: frozenset[str] = frozenset({
    "co.uk", "co.in", "co.nz", "co.za", "co.jp", "co.kr",
    "com.au", "com.br", "com.cn", "com.hk", "com.sg", "com.tw",
    "org.uk", "net.au",
})

# Brand names that should be treated as trusted regardless of their TLD
_TRUSTED_BRANDS: frozenset[str] = frozenset({
    "wirecutter", "rtings", "techradar", "cnet", "tomsguide", "pcmag",
    "theverge", "engadget", "wired", "arstechnica", "consumerreports",
    "goodhousekeeping", "forbes", "businessinsider", "bloomberg",
    "soundguys", "headfonics", "whathifi", "headphonesaddict",
    "91mobiles", "smartprix", "gadgets360", "digit", "techpp",
    "gsmarena", "anandtech", "notebookcheck", "dxomark",
    "which", "trustedreviews", "expertreviews",
    "runnersworld", "runnerworld",
    "allure", "byrdie", "cosmopolitan", "menshealth",
    "sleepfoundation", "sleepopolis", "mattressclarity",
})

_GOOD_BRANDS: frozenset[str] = frozenset({
    "amazon", "bestbuy", "flipkart",
})


# ── Numeric authority scores by domain (O1 fix) ───────────────────────────────
# Scale: 0–100. Used by get_authority_score().

_AUTHORITY_SCORES: dict[str, int] = {
    # Gold standard (90–100)
    "rtings.com":           97,
    "wirecutter.com":       95,
    "consumerreports.org":  93,
    "arstechnica.com":      90,
    "gsmarena.com":         89,
    "notebookcheck.net":    88,
    "dxomark.com":          87,
    # Major editorial (80–89)
    "wired.com":            88,
    "which.co.uk":          86,
    "soundguys.com":        85,
    "headfonics.com":       83,
    "pcmag.com":            83,
    "anandtech.com":        83,
    "techradar.com":        82,
    "cnet.com":             82,
    "tomsguide.com":        82,
    "whathifi.com":         81,
    "theverge.com":         80,
    "engadget.com":         80,
    # Good editorial (65–79)
    "91mobiles.com":        78,
    "gadgets360.com":       76,
    "trustedreviews.co.uk": 76,
    "sleepfoundation.org":  80,
    "sleepopolis.com":      75,
    "mattressclarity.com":  73,
    "digit.in":             72,
    "expertreviews.co.uk":  72,
    "smartprix.com":        70,
    "bloomberg.com":        70,
    "wsj.com":              70,
    "allure.com":           75,
    "byrdie.com":           72,
    "goodhousekeeping.com": 74,
    "indianexpress.com":    65,
    "livemint.com":         65,
    "techpp.com":           65,
    "menshealth.com":       68,
    "womenshealthmag.com":  68,
    "runnersworld.com":     72,
    "runnerworld.com":      72,
    "headphonesaddict.com": 65,
    "sfgate.com":           65,
    "health.com":           65,
    "today.com":            65,
    "cosmopolitan.com":     62,
    "thestrategist.com":    68,
    "nymag.com":            70,
    "ndtv.com":             65,
    # Paywalls (quality content but limited access)
    "nytimes.com":          72,
    "forbes.com":           65,
    "businessinsider.com":  62,
    # Commerce with reviews
    "amazon.com":           45,
    "amazon.in":            45,
    "amazon.co.uk":         45,
    "bestbuy.com":          45,
    "flipkart.com":         42,
    # Community (not editorial authority)
    "reddit.com":            0,   # O3: handled by get_source_type, not authority
    "quora.com":            15,
    # Mixed/blog quality
    "medium.com":           30,
    "substack.com":         30,
    "youtube.com":          35,
}

# ── Bug 3 fix: path prefixes that indicate affiliate content on otherwise-trusted domains ─

_AFFILIATE_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "forbes.com":          ("/advisor/", "/coupons/", "/deals/"),
    "cnet.com":            ("/deals/", "/coupons/"),
    "pcmag.com":           ("/deals/",),
    "businessinsider.com": ("/deals/", "/coupons/"),
    "techradar.com":       ("/deals/",),
    "tomsguide.com":       ("/deals/",),
    "engadget.com":        ("/deals/",),
    "theverge.com":        ("/deals/",),
}

# ── Category-specific authority adjustments (O2 fix) ─────────────────────────
# Positive: domain is especially authoritative for this category.
# Negative: domain is less relevant.

_CATEGORY_ADJUSTMENTS: dict[str, dict[str, int]] = {
    "electronics/tv": {
        "rtings.com": +5, "soundguys.com": -20, "sleepfoundation.org": -30, "allure.com": -30,
    },
    "electronics/headphones": {
        "rtings.com": +3, "soundguys.com": +10, "headfonics.com": +10, "whathifi.com": +7,
        "headphonesaddict.com": +8, "sleepfoundation.org": -30,
    },
    "electronics/earbuds": {
        "rtings.com": +2, "soundguys.com": +10, "headfonics.com": +8, "whathifi.com": +5,
        "headphonesaddict.com": +8, "sleepfoundation.org": -30,
    },
    "electronics/laptop": {
        "notebookcheck.net": +10, "anandtech.com": +7, "rtings.com": +3,
        "gsmarena.com": -10, "sleepfoundation.org": -30,
    },
    "electronics/phone": {
        "gsmarena.com": +10, "91mobiles.com": +8, "dxomark.com": +8,
        "notebookcheck.net": +5, "rtings.com": -5, "sleepfoundation.org": -30,
    },
    "bedding": {
        "sleepfoundation.org": +12, "sleepopolis.com": +10, "mattressclarity.com": +10,
        "rtings.com": -20, "soundguys.com": -30, "gsmarena.com": -30,
    },
    "skincare": {
        "allure.com": +12, "byrdie.com": +12, "goodhousekeeping.com": +7,
        "rtings.com": -35, "gsmarena.com": -35, "soundguys.com": -35,
    },
    "fitness": {
        "runnersworld.com": +12, "runnerworld.com": +12, "menshealth.com": +8,
        "rtings.com": -20, "soundguys.com": -20,
    },
}


# ── Exact and pattern-based junk detection ────────────────────────────────────

JUNK_DOMAINS_EXACT: frozenset[str] = frozenset({
    "heartcosy.com",
    "jamesfurnituredeals.com",
    "accio.com",
    "shopnow.hindustantimes.com",
    "techhubb.blog",
})

# Bug 2 fix: patterns are matched at word boundaries only (start of domain or after hyphen)
# so "thebestproductsever.com" is NOT flagged as junk — "bestproducts" is embedded mid-word.
JUNK_DOMAIN_PATTERNS: tuple[str, ...] = (
    "bestproducts",
    "top10products",
    "best10",
    "buyersguide",
    "reviewsofbest",
    "bestreviewed",
    "top5best",
    "mybest",
    "bestof2024",
    "bestof2025",
    "bestof2026",
    "buynow",
    "dealstoday",
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_domain(url: str) -> str:
    """Extract clean domain from URL (no www., lowercase)."""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _extract_brand(domain: str) -> str:
    """
    Extract the registrable brand name, handling compound TLDs (Bug 1).
    'wired.co.uk' → 'wired', 'techradar.com.au' → 'techradar',
    'reviews.pcmag.com' → 'pcmag'.
    """
    for ctld in _COMPOUND_TLDS:
        if domain.endswith("." + ctld):
            remainder = domain[: -(len(ctld) + 1)]
            return remainder.rsplit(".", 1)[-1]
    # Standard single TLD: take second-to-last label
    parts = domain.rsplit(".", 1)
    base = parts[0]
    return base.rsplit(".", 1)[-1] if "." in base else base


def _has_affiliate_path(domain: str, url: str) -> bool:
    """Return True if the URL path signals affiliate content on a trusted domain (Bug 3)."""
    prefixes = _AFFILIATE_PATH_PREFIXES.get(domain)
    if not prefixes:
        return False
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return any(path.startswith(p) for p in prefixes)


def _junk_pattern_match(domain_without_tld: str) -> str | None:
    """
    Check junk patterns at word boundaries only (Bug 2 fix).
    The character immediately before the pattern must NOT be an alpha character,
    preventing 'bestproducts' from matching inside 'thebestproductsguide'.
    Returns the matched pattern name, or None.
    """
    for pattern in JUNK_DOMAIN_PATTERNS:
        idx = domain_without_tld.find(pattern)
        while idx >= 0:
            before_ok = (idx == 0) or (not domain_without_tld[idx - 1].isalpha())
            if before_ok:
                return pattern
            idx = domain_without_tld.find(pattern, idx + 1)
    return None


def _is_trusted(domain: str) -> bool:
    """True if domain or its brand name is in the trusted set."""
    for trusted in TRUSTED_DOMAINS:
        if domain == trusted or domain.endswith("." + trusted):
            return True
    return _extract_brand(domain) in _TRUSTED_BRANDS


def _is_good(domain: str) -> bool:
    for good in GOOD_DOMAINS:
        if domain == good or domain.endswith("." + good):
            return True
    return _extract_brand(domain) in _GOOD_BRANDS


# ── Public API ────────────────────────────────────────────────────────────────

def should_skip(url: str) -> tuple[bool, str]:
    """
    Returns (should_skip, reason).
    should_skip=True ONLY for unambiguous junk.
    When in doubt → (False, "kept: uncertain")
    """
    domain = _get_domain(url)
    if not domain:
        return False, "kept: could not parse domain"

    # 1. Trusted domains — never skip, even if path looks affiliate-y
    if _is_trusted(domain):
        return False, f"kept: trusted domain ({domain})"

    # 2. Good / community / blog domains — never skip
    if _is_good(domain) or domain in _COMMUNITY_DOMAINS or domain in _BLOG_DOMAINS:
        return False, f"kept: known domain ({domain})"

    # 3. Exact junk list
    if domain in JUNK_DOMAINS_EXACT:
        return True, f"skipped: known junk domain ({domain})"

    # 4. Junk patterns at word boundaries (Bug 2 fix)
    domain_without_tld = domain.rsplit(".", 1)[0] if "." in domain else domain
    matched = _junk_pattern_match(domain_without_tld)
    if matched:
        return True, f"skipped: junk pattern '{matched}' in domain"

    return False, "kept: no junk signals found"


def get_authority_tier(url: str) -> str:
    """
    Returns authority tier: "trusted" / "good" / "community" / "unknown" / "low".
    Derived from get_authority_score() for consistency.
    """
    domain = _get_domain(url)
    if not domain:
        return "unknown"

    # O3 fix: community sources get their own type, not a quality tier
    if domain in _COMMUNITY_DOMAINS or _extract_brand(domain) in {"reddit", "quora"}:
        return "community"

    score = get_authority_score(url)
    if score >= 75:
        return "trusted"
    if score >= 40:
        return "good"
    if score >= 20:
        return "unknown"
    return "low"


def get_authority_score(url: str, category: str | None = None) -> int:
    """
    Return numeric authority score 0–100 (O1 fix).
    Higher = more authoritative for this product category.

    Optionally pass `category` (e.g. "electronics/headphones") for
    category-specific adjustments (O2 fix).
    """
    domain = _get_domain(url)
    if not domain:
        return 25  # unknown

    # Path-based downgrade for affiliate sections on trusted domains (Bug 3 fix)
    affiliate_path = _has_affiliate_path(domain, url)

    # Look up base score — check exact domain first, then brand family
    base_score = _AUTHORITY_SCORES.get(domain)
    if base_score is None:
        brand = _extract_brand(domain)
        # Find the base domain entry for this brand (Bug 1 fix)
        for d, s in _AUTHORITY_SCORES.items():
            if _extract_brand(d) == brand:
                base_score = s
                break
        else:
            # Check sets
            if brand in _TRUSTED_BRANDS or _is_trusted(domain):
                base_score = 72
            elif brand in _GOOD_BRANDS or _is_good(domain):
                base_score = 45
            elif domain in _BLOG_DOMAINS:
                base_score = 30
            elif domain in _COMMUNITY_DOMAINS:
                base_score = 0
            else:
                base_score = 25  # unknown domain

    score = base_score

    # Affiliate path penalty (Bug 3 fix)
    if affiliate_path:
        score = max(0, score - 30)
        logger.debug("[source_filter] %s: affiliate path → score %d", domain, score)

    # Category-specific adjustment (O2 fix)
    if category:
        # Try exact match, then prefix match (e.g. "electronics" matches "electronics/laptop")
        adjustments = _CATEGORY_ADJUSTMENTS.get(category) or {}
        if not adjustments:
            prefix = category.split("/")[0]
            adjustments = _CATEGORY_ADJUSTMENTS.get(prefix, {})
        adj = adjustments.get(domain, 0)
        if adj == 0:
            adj = adjustments.get(_extract_brand(domain), 0)
        score = max(0, min(100, score + adj))

    return score


def get_source_type(url: str) -> str:
    """
    Return the source type — callers can treat community and editorial signals differently.
    "editorial"  → professional review publication
    "community"  → Reddit, Quora, forums
    "commerce"   → retailer with user reviews (Amazon, Flipkart)
    "blog"       → Medium, Substack, personal blogs
    "unknown"    → can't determine
    """
    domain = _get_domain(url)
    if not domain:
        return "unknown"
    brand = _extract_brand(domain)

    if domain in _COMMUNITY_DOMAINS or brand in {"reddit", "quora"}:
        return "community"
    if domain in _BLOG_DOMAINS or brand in {"medium", "substack", "wordpress", "blogspot"}:
        return "blog"
    if domain in GOOD_DOMAINS or brand in _GOOD_BRANDS:
        return "commerce"
    if _is_trusted(domain):
        return "editorial"
    # Score-based fallback
    score = get_authority_score(url)
    if score >= 60:
        return "editorial"
    if score >= 40:
        return "commerce"
    return "unknown"


def filter_review_urls(urls: list[str]) -> list[str]:
    """Filter a list of review URLs, removing junk. Returns clean list with audit log."""
    kept = []
    for url in urls:
        skip, reason = should_skip(url)
        domain = _get_domain(url)
        if skip:
            logger.info("[source_filter] SKIP %s — %s", domain, reason)   # O4: was print()
        else:
            kept.append(url)
    removed = len(urls) - len(kept)
    if removed > 0:
        logger.info("[source_filter] removed %d junk URLs, kept %d", removed, len(kept))
    return kept
