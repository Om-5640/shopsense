"""
Phase 1: Multi-source review URL discovery.

Extends Gemini grounding with expert editorial search and news search.
All sources merge into ReviewCandidate objects, deduplicated before scraping.

Existing Gemini grounding flow is NEVER modified — this is purely additive.
New sources are only tried when google_search (Serper) is configured.
Falls back silently if any new source fails.

Source confidence levels:
  gemini_grounding   0.90  — Gemini specifically chose these with live search
  expert_editorial   0.85  — matched known expert domain in search results
  news               0.70  — recent coverage via general search
  serper_fallback    0.65  — Serper-only when Gemini returned nothing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ReviewCandidate:
    url: str
    source_type: str            # gemini_grounding | expert_editorial | news | serper_fallback
    domain: str = ""
    title: str = ""
    discovered_from: str = ""   # gemini | serper_expert | serper_news | serper_fallback
    retrieval_confidence: float = 0.80

    def __post_init__(self) -> None:
        if not self.domain and self.url:
            self.domain = _domain(self.url)


# Expert editorial domains — used to score Serper results
_EXPERT_DOMAINS = frozenset({
    "rtings.com", "tomsguide.com", "techradar.com", "wirecutter.com",
    "notebookcheck.net", "pcmag.com", "theverge.com", "engadget.com",
    "soundguys.com", "displayninja.com", "laptopmag.com",
    "androidauthority.com", "digitaltrends.com", "whathifi.com",
    "91mobiles.com", "gadgets360.com", "anandtech.com", "hardwareunboxed.com",
    "dxomark.com", "gsmarena.com", "headfonics.com", "trustedreviews.com",
    "expertreviews.co.uk", "which.co.uk", "cnet.com", "arstechnica.com",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wrap_gemini_urls(urls: list[str]) -> list[ReviewCandidate]:
    """Wrap existing Gemini grounding URLs as ReviewCandidate objects (no-op for existing code)."""
    return [
        ReviewCandidate(
            url=u,
            source_type="gemini_grounding",
            discovered_from="gemini",
            retrieval_confidence=0.90,
        )
        for u in urls
    ]


def fetch_expert_editorial_candidates(query: str, limit: int = 5) -> list[ReviewCandidate]:
    """
    Search for reviews from known expert editorial domains via Serper.
    Uses semantic search — no per-category site lists.
    """
    try:
        return _expert_search(query, limit)
    except Exception as e:
        print(f"[candidates] expert editorial search failed (non-fatal): {e}")
        return []


def fetch_news_candidates(query: str, limit: int = 5) -> list[ReviewCandidate]:
    """Search for recent news coverage: reviews, hands-on, buying guides."""
    try:
        return _news_search(query, limit)
    except Exception as e:
        print(f"[candidates] news search failed (non-fatal): {e}")
        return []


def merge_and_deduplicate(
    *candidate_lists: list[ReviewCandidate],
) -> list[ReviewCandidate]:
    """
    Merge multiple candidate lists and deduplicate by normalized URL.
    Earlier lists (higher confidence) win on URL conflicts.
    """
    seen: set[str] = set()
    merged: list[ReviewCandidate] = []
    for candidates in candidate_lists:
        for c in candidates:
            norm = _normalize(c.url)
            if norm and norm not in seen:
                seen.add(norm)
                merged.append(c)
    return merged


def retrieve_review_candidates(
    query: str,
    gemini_urls: list[str] | None = None,
    extra_limit: int = 5,
) -> list[ReviewCandidate]:
    """
    Full multi-source retrieval entry point.

    gemini_urls: URLs already found by Gemini (may be empty list or None).
    extra_limit: max additional URLs to fetch per supplementary source.

    Returns deduplicated merged list, Gemini sources first.
    """
    gemini = wrap_gemini_urls(gemini_urls or [])
    expert = fetch_expert_editorial_candidates(query, limit=extra_limit)
    news = fetch_news_candidates(query, limit=extra_limit)
    return merge_and_deduplicate(gemini, expert, news)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expert_search(query: str, limit: int) -> list[ReviewCandidate]:
    import google_search
    if not google_search.is_configured():
        return []

    results = google_search.search(f"{query} in-depth review measurements test", num=limit * 3)
    candidates: list[ReviewCandidate] = []
    seen: set[str] = set()
    for r in results:
        link = r.get("link", "")
        if not link or link in seen:
            continue
        dom = _domain(link)
        if dom not in _EXPERT_DOMAINS:
            continue
        seen.add(link)
        candidates.append(ReviewCandidate(
            url=link,
            source_type="expert_editorial",
            title=r.get("title", ""),
            discovered_from="serper_expert",
            retrieval_confidence=0.85,
        ))
        if len(candidates) >= limit:
            break
    return candidates


def _news_search(query: str, limit: int) -> list[ReviewCandidate]:
    import google_search
    if not google_search.is_configured():
        return []

    queries = [f"{query} review", f"{query} buying guide", f"{query} hands on"]
    candidates: list[ReviewCandidate] = []
    seen: set[str] = set()

    for q in queries:
        for r in google_search.search(q, num=limit):
            link = r.get("link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            candidates.append(ReviewCandidate(
                url=link,
                source_type="news",
                title=r.get("title", ""),
                discovered_from="serper_news",
                retrieval_confidence=0.70,
            ))
        if len(candidates) >= limit:
            break

    return candidates[:limit]


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _normalize(url: str) -> str:
    return url.split("#")[0].rstrip("/").lower()
