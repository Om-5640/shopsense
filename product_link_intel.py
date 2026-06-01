"""
Product Link Intelligence Engine — Phases 2, 3, 6, 7, 8, 9, 10, 11, 13

Orchestrates candidate collection, matching, clustering, consensus scoring,
and confidence scoring on top of price_fetcher's Serper results.

All functions are fail-safe: any exception is caught and the caller falls back
to the existing (pre-intelligence) behavior. The user never loses purchase links.

Feature flag: LINK_INTEL_ENABLED = True (can be toggled to False at runtime)

Usage (internal — called from price_fetcher._fetch_one_product):
    from product_link_intel import run_link_intelligence, LINK_INTEL_ENABLED
    intel = run_link_intelligence(canonical, retailers_with_candidates, price_field)
    if intel and intel.confidence >= MIN_CONFIDENCE_THRESHOLD:
        output["intelligence"] = intel.to_dict()
"""

import re
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from product_canonicalizer import CanonicalProduct, extract_product_attributes
from product_matcher import match_product_candidate

__all__ = [
    "LINK_INTEL_ENABLED",
    "MIN_CONFIDENCE_THRESHOLD",
    "ProductCandidate",
    "LinkIntelResult",
    "run_link_intelligence",
]

_logger = logging.getLogger(__name__)

# ── Feature flags ─────────────────────────────────────────────────────────────
LINK_INTEL_ENABLED = True
MIN_CONFIDENCE_THRESHOLD = 0.72  # Below this → status="uncertain", fallback behaviour

# ── Source trust scores (Phase 11) ───────────────────────────────────────────
_SOURCE_TRUST: dict[str, float] = {
    "amazon.in":          0.95,
    "amazon.com":         0.95,
    "flipkart.com":       0.90,
    "samsung.com":        0.98,
    "samsung.com/in":     0.98,
    "apple.com":          0.98,
    "lenovo.com":         0.95,
    "asus.com":           0.95,
    "sony.co.in":         0.93,
    "sony.com":           0.93,
    "bestbuy.com":        0.88,
    "croma.com":          0.80,
    "reliancedigital.in": 0.80,
    "vijaysales.com":     0.75,
    "tatacliq.com":       0.78,
    "poorvika.com":       0.72,
}

# Priority order for offer ranking (Phase 10)
_RETAILER_PRIORITY: dict[str, int] = {
    "amazon.in":    1,
    "amazon.com":   1,
    "flipkart.com": 2,
    "samsung.com":  3,
    "apple.com":    3,
    "lenovo.com":   3,
    "asus.com":     3,
    "bestbuy.com":  2,
    "croma.com":    4,
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ProductCandidate:
    """Phase 3: One candidate result from a marketplace."""
    retailer_name: str
    title: str
    url: str
    price: float | None
    rating: float | None
    review_count: int | None
    image_url: str | None
    mrp: float | None
    domain: str
    raw: dict                   # original retailer dict from price_fetcher
    match_score: float = 0.0
    storage_mismatch: bool = False
    cluster_id: str = "unknown"


@dataclass
class LinkIntelResult:
    """Final result returned by run_link_intelligence()."""
    best_candidate: ProductCandidate | None
    all_candidates: list[ProductCandidate]
    winning_cluster: list[ProductCandidate]
    consensus_score: float          # 0.0–1.0
    match_score: float              # best candidate's match score
    source_trust: float             # trust of winning source
    price_consistency: float        # 0.0–1.0
    confidence: float               # final combined score
    status: str                     # "confident" | "uncertain" | "fallback"
    canonical: CanonicalProduct

    def to_dict(self) -> dict:
        c = self.best_candidate
        return {
            "confidence":         round(self.confidence, 3),
            "consensus_score":    round(self.consensus_score, 3),
            "match_score":        round(self.match_score, 3),
            "source_trust":       round(self.source_trust, 3),
            "price_consistency":  round(self.price_consistency, 3),
            "status":             self.status,
            "canonical": {
                "brand":       self.canonical.brand,
                "model":       self.canonical.model,
                "storage":     self.canonical.storage,
                "ram":         self.canonical.ram,
                "color":       self.canonical.color,
                "variant":     self.canonical.variant,
                "screen_size": self.canonical.screen_size,
                "canonical_name": self.canonical.canonical_name,
                "parse_confidence": self.canonical.parse_confidence,
            },
            "best_url":   c.url if c else None,
            "best_title": c.title if c else None,
            "best_image": c.image_url if c else None,
            "best_rating":      c.rating if c else None,
            "best_review_count": c.review_count if c else None,
        }


# ── Phase 7: Consensus Validation ─────────────────────────────────────────────

def compute_consensus_score(candidates: list[ProductCandidate]) -> float:
    """
    Measure how many independent marketplaces agree on the same storage variant.
    Amazon 512GB + Flipkart 512GB + Brand 512GB → 1.0
    Amazon 512GB + Flipkart 256GB + Brand 512GB → 0.67
    """
    if not candidates:
        return 0.5

    # Group by domain (one vote per domain)
    domain_storage: dict[str, str] = {}
    for c in candidates:
        if c.domain not in domain_storage:
            attrs = extract_product_attributes(c.title)
            domain_storage[c.domain] = attrs.get("storage") or "unknown"

    if len(domain_storage) < 2:
        return 0.6  # single source — partial confidence

    storage_votes: dict[str, int] = {}
    for storage in domain_storage.values():
        storage_votes[storage] = storage_votes.get(storage, 0) + 1

    total = sum(storage_votes.values())
    max_agree = max(storage_votes.values())
    return round(max_agree / total, 3)


# ── Phase 8: Confidence Scoring ───────────────────────────────────────────────

def compute_link_confidence(
    match_score: float,
    consensus_score: float,
    source_trust: float,
    price_consistency: float,
) -> float:
    """
    confidence = match×0.45 + consensus×0.35 + trust×0.15 + price_consistency×0.05
    """
    return round(
        match_score       * 0.45
        + consensus_score   * 0.35
        + source_trust      * 0.15
        + price_consistency * 0.05,
        3,
    )


def _compute_price_consistency(candidates: list[ProductCandidate]) -> float:
    """Low price variance → high consistency score."""
    prices = [c.price for c in candidates if c.price and c.price > 0]
    if len(prices) < 2:
        return 0.8
    avg = sum(prices) / len(prices)
    if avg <= 0:
        return 0.5
    variance = sum((p - avg) ** 2 for p in prices) / len(prices)
    cv = (variance ** 0.5) / avg   # coefficient of variation
    # CV < 0.05 → 1.0, CV > 0.40 → 0.0
    return round(max(0.0, min(1.0, 1.0 - cv / 0.40)), 3)


# ── Phase 6: Product Clustering ───────────────────────────────────────────────

def _cluster_by_storage(
    candidates: list[ProductCandidate],
    target_storage: str | None,
) -> list[list[ProductCandidate]]:
    """
    Group candidates by storage variant.
    Cluster matching target storage comes first.
    """
    buckets: dict[str, list[ProductCandidate]] = {}
    for c in candidates:
        attrs = extract_product_attributes(c.title)
        storage_key = attrs.get("storage") or "unknown"
        c.cluster_id = storage_key
        buckets.setdefault(storage_key, []).append(c)

    def priority(item: tuple[str, list]) -> int:
        k = item[0]
        if k == target_storage:
            return 0
        if k == "unknown":
            return 2
        return 1

    sorted_buckets = sorted(buckets.items(), key=priority)
    return [v for _, v in sorted_buckets]


# ── Phase 10: Offer Ranking ───────────────────────────────────────────────────

def rank_offers(candidates: list[ProductCandidate]) -> list[ProductCandidate]:
    """
    Rank offers within a cluster.
    Factors: source trust, retailer priority, availability, rating.
    Does NOT simply choose lowest price.
    """
    def score(c: ProductCandidate) -> float:
        trust    = _SOURCE_TRUST.get(c.domain, 0.55)
        priority = 1.0 / max(1, _RETAILER_PRIORITY.get(c.domain, 5))
        has_price = 0.15 if c.price else 0.0
        rating_bonus = 0.0
        if c.rating:
            rating_bonus = (max(0.0, c.rating - 3.0) / 2.0) * 0.08
        image_bonus = 0.05 if c.image_url else 0.0
        return trust * 0.55 + priority * 0.25 + has_price + rating_bonus + image_bonus

    return sorted(candidates, key=score, reverse=True)


# ── Phase 11: Brand Store Validation (additive) ───────────────────────────────

_BRAND_DOMAINS: dict[str, str] = {
    "Samsung":  "samsung.com",
    "Apple":    "apple.com",
    "Lenovo":   "lenovo.com",
    "ASUS":     "asus.com",
    "Sony":     "sony.com",
    "Dell":     "dell.com",
    "HP":       "hp.com",
    "Acer":     "acer.com",
    "MSI":      "msi.com",
}

def _brand_store_bonus(
    canonical: CanonicalProduct,
    candidates: list[ProductCandidate],
) -> float:
    """Return a small consensus/confidence bonus when brand store is present."""
    if not canonical.brand:
        return 0.0
    expected_domain = _BRAND_DOMAINS.get(canonical.brand, "")
    if not expected_domain:
        return 0.0
    for c in candidates:
        if expected_domain in c.domain and not c.storage_mismatch:
            return 0.04   # +4% bonus — brand site agrees
    return 0.0


# ── Main entry point ──────────────────────────────────────────────────────────

def run_link_intelligence(
    canonical: CanonicalProduct,
    retailer_results: list[dict],
    price_field: str = "price_inr",
) -> LinkIntelResult | None:
    """
    Phases 2–13: Full intelligence pipeline.

    canonical        — CanonicalProduct parsed from the searched product name
    retailer_results — list of retailer dicts from price_fetcher (each may have
                       a "_candidates" key with the top-5 raw Serper results)
    price_field      — "price_inr" | "price_usd"

    Returns None on any error (caller falls back to current behavior).
    """
    if not LINK_INTEL_ENABLED:
        return None

    try:
        # ── Phase 3: Collect candidates from all retailers ────────────────────
        candidates: list[ProductCandidate] = []

        for retailer in retailer_results:
            # Each retailer dict may have "_candidates" = list of top-N raw results
            raw_list: list[dict] = retailer.get("_candidates") or []
            if not raw_list and retailer.get("url"):
                raw_list = [retailer]   # wrap single result for backward compat

            for raw in raw_list[:5]:   # cap at 5 per retailer (Phase 3)
                url   = raw.get("url", "")
                title = raw.get("title", "") or raw.get("name", "")
                if not title:
                    continue

                domain = urlparse(url).netloc.lstrip("www.") if url else ""
                price  = raw.get(price_field) or raw.get("price_inr") or raw.get("price_usd")

                # Parse review_count safely (Serper returns strings like "1,234")
                rc_raw = raw.get("review_count")
                if rc_raw:
                    try:
                        review_count: int | None = int(re.sub(r"[^\d]", "", str(rc_raw)))
                    except ValueError:
                        review_count = None
                else:
                    review_count = None

                pc = ProductCandidate(
                    retailer_name=raw.get("name", domain),
                    title=title,
                    url=url,
                    price=float(price) if price else None,
                    rating=raw.get("rating"),
                    review_count=review_count,
                    image_url=raw.get("image_url"),
                    mrp=raw.get("mrp_inr"),
                    domain=domain,
                    raw=raw,
                )

                # Phase 5: run matcher
                result = match_product_candidate(canonical, title)
                pc.match_score     = result.overall_match_score
                pc.storage_mismatch = result.storage_mismatch
                candidates.append(pc)

        if not candidates:
            return None

        # Phase 9: filter hard mismatches, but keep them as fallback
        good = [c for c in candidates if not c.storage_mismatch]
        working = good if good else candidates

        # Sort by match score
        working.sort(key=lambda c: c.match_score, reverse=True)

        # Phase 6: cluster by storage
        clusters = _cluster_by_storage(working, canonical.storage)
        winning_cluster = clusters[0] if clusters else working

        # Phase 10: rank offers within winning cluster
        ranked = rank_offers(winning_cluster)
        best   = ranked[0] if ranked else None

        # Phase 7: consensus from ALL candidates (cross-marketplace agreement)
        consensus = compute_consensus_score(working[:12])

        # Brand store bonus (Phase 11)
        brand_bonus = _brand_store_bonus(canonical, working)
        consensus   = min(1.0, consensus + brand_bonus)

        # Phase 8: confidence
        source_trust      = _SOURCE_TRUST.get(best.domain if best else "", 0.55)
        match_sc          = best.match_score if best else 0.0
        price_consistency = _compute_price_consistency(winning_cluster)

        confidence = compute_link_confidence(
            match_sc,
            consensus,
            source_trust,
            price_consistency,
        )

        # Phase 9: evidence threshold
        status = "confident" if confidence >= MIN_CONFIDENCE_THRESHOLD else "uncertain"

        return LinkIntelResult(
            best_candidate=best,
            all_candidates=candidates,
            winning_cluster=winning_cluster,
            consensus_score=consensus,
            match_score=match_sc,
            source_trust=source_trust,
            price_consistency=price_consistency,
            confidence=confidence,
            status=status,
            canonical=canonical,
        )

    except Exception as exc:
        _logger.debug("[link_intel] pipeline failed (non-fatal): %s", exc)
        return None
