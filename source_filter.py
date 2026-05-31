"""
Source authority and affiliate filtering.

Philosophy:
- Conservative: when in doubt, KEEP the site. A false negative (missing good content)
  is worse than a false positive (including mediocre content).
- Whitelist always wins: if a domain is on the trusted list, it NEVER gets filtered
  regardless of what the pattern matcher says.
- Only block sites that are unambiguously affiliate/SEO junk with zero editorial value.

Two outputs:
1. should_skip(url) → True only for clear junk
2. get_authority_tier(url) → "trusted" / "good" / "unknown" / "low"
   Used by the analyzer to weight sources appropriately.
"""

from urllib.parse import urlparse


# ---- Whitelist: these NEVER get filtered, always trusted ----
# Add to this list freely. When in doubt, add here.

TRUSTED_DOMAINS = {
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
    "trustedreviews.com",
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
}

# ---- Good tier: reputable but not top-tier authorities ----
# These get slightly lower weight in the analyzer but are NOT filtered.

GOOD_DOMAINS = {
    "amazon.com",           # reviews section is useful
    "bestbuy.com",          # review aggregation
    "flipkart.com",         # reviews section India
    "reddit.com",           # handled separately
    "youtube.com",          # we don't scrape these anyway
    "medium.com",           # mixed quality, keep
    "substack.com",         # mixed quality, keep
}


# ---- Blacklist patterns: ONLY the most unambiguous affiliate junk ----
# Rules:
# 1. Only add if 95%+ of sites matching this pattern are junk
# 2. If there's ANY doubt, don't add
# 3. Check whitelist first before blacklisting

# Exact junk domains (confirmed worthless)
JUNK_DOMAINS_EXACT = {
    "heartcosy.com",
    "jamesfurnituredeals.com",
    "accio.com",
    "shopnow.hindustantimes.com",  # not real editorial
    "techhubb.blog",               # thin affiliate blog
}

# Domain patterns that indicate junk (only match full domain, not subdomains of trusted)
# These are VERY conservative patterns — only match obvious keyword-stuffed domains
JUNK_DOMAIN_PATTERNS = [
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
]


def _get_domain(url: str) -> str:
    """Extract clean domain from URL."""
    try:
        netloc = urlparse(url).netloc.lower()
        # Strip www. and www2. etc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def should_skip(url: str) -> tuple[bool, str]:
    """
    Returns (should_skip, reason).
    should_skip=True ONLY for unambiguous junk.
    When in doubt → (False, "kept: uncertain")

    Design: whitelist check runs first. If domain is trusted, we NEVER skip.
    """
    domain = _get_domain(url)
    if not domain:
        return False, "kept: could not parse domain"

    # 1. Whitelist always wins — trusted domains are never skipped
    for trusted in TRUSTED_DOMAINS:
        if domain == trusted or domain.endswith("." + trusted):
            return False, f"kept: trusted domain ({trusted})"

    # 2. Good domains are also never skipped
    for good in GOOD_DOMAINS:
        if domain == good or domain.endswith("." + good):
            return False, f"kept: good domain ({good})"

    # 3. Check exact junk list
    if domain in JUNK_DOMAINS_EXACT:
        return True, f"skipped: known junk domain ({domain})"

    # 4. Check junk patterns — ONLY on the domain itself, never subdomains of trusted
    domain_without_tld = domain.rsplit(".", 1)[0] if "." in domain else domain
    for pattern in JUNK_DOMAIN_PATTERNS:
        if pattern in domain_without_tld:
            return True, f"skipped: junk pattern '{pattern}' in domain"

    # 5. Default: keep it
    return False, "kept: no junk signals found"


def get_authority_tier(url: str) -> str:
    """
    Returns authority tier for the analyzer to weight sources.
    "trusted"  → top-tier editorial (Wirecutter, RTINGS, etc.)
    "good"     → reputable but not authority (Amazon reviews, Medium)
    "unknown"  → can't determine, treat neutrally
    "low"      → survived filter but shows some low-quality signals
    """
    domain = _get_domain(url)
    if not domain:
        return "unknown"

    for trusted in TRUSTED_DOMAINS:
        if domain == trusted or domain.endswith("." + trusted):
            return "trusted"

    for good in GOOD_DOMAINS:
        if domain == good or domain.endswith("." + good):
            return "good"

    return "unknown"


def filter_review_urls(urls: list[str]) -> list[str]:
    """Filter a list of review URLs, removing junk. Returns clean list with audit log."""
    kept = []
    for url in urls:
        skip, reason = should_skip(url)
        domain = _get_domain(url)
        if skip:
            print(f"   [filter] SKIP {domain} — {reason}")
        else:
            kept.append(url)
    removed = len(urls) - len(kept)
    if removed > 0:
        print(f"   [filter] removed {removed} junk URLs, kept {len(kept)}")
    return kept
