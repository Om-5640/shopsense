"""
Phase 9: Structured evidence packaging for the analyzer.

Transforms enriched review dicts (after all Phase 1–8 enhancements) into
ReviewEvidence objects that the analyzer can reason over as structured data
rather than raw article dumps.

Backward compatible: raw content is always preserved in the evidence,
so existing analyzer prompts that read raw text still work.

Usage:
    from review_evidence import build_evidence_block, format_evidence_for_prompt

    evidence = build_evidence_block(review_dict)
    prompt_section = format_evidence_for_prompt(evidence_list, conflict_signals)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReviewEvidence:
    # Identity
    url: str
    domain: str
    source_type: str = "gemini_grounding"   # gemini_grounding | expert_editorial | news | youtube

    # Scoring
    trust_score: float = 0.50
    freshness_score: float = 0.50
    review_rank_score: float = 0.50

    # Content
    title: str = ""
    raw_content: str = ""                   # always preserved, never deleted
    structured_review: Optional[dict] = None

    # Metadata
    published_date: Optional[str] = None
    canonical_product_id: Optional[str] = None
    authority_tier: str = "unknown"         # backward-compat string for existing prompts


def build_evidence_block(review: dict) -> ReviewEvidence:
    """
    Convert an enriched review dict (from fetch_review_page / fetch_youtube_reviews)
    into a ReviewEvidence object.

    Falls back gracefully: missing fields use safe defaults.
    """
    return ReviewEvidence(
        url=review.get("url", ""),
        domain=review.get("domain", ""),
        source_type=review.get("source_type", "gemini_grounding"),
        trust_score=review.get("domain_trust_score", 0.50),
        freshness_score=review.get("freshness_score", 0.50),
        review_rank_score=review.get("review_rank_score", 0.50),
        title=review.get("title", ""),
        raw_content=review.get("content", "") or review.get("transcript_snippet", ""),
        structured_review=review.get("structured_review"),
        published_date=review.get("published_date"),
        canonical_product_id=review.get("canonical_product_id"),
        authority_tier=review.get("authority_tier", "unknown"),
    )


def format_evidence_for_prompt(
    evidence_list: list[ReviewEvidence],
    conflict_signals: list[dict] | None = None,
) -> str:
    """
    Render evidence list as a structured prompt section.

    Format:
      [SOURCE 1 — rtings.com | TRUSTED | fresh: 1.00 | rank: 0.91]
      Title: ...
      Pros: ...  Cons: ...  Verdict: ...
      ---RAW---
      <content>

    If conflict_signals are provided, a CONFLICTS section is prepended so
    the analyzer knows which aspects are disputed.
    """
    parts: list[str] = []

    if conflict_signals:
        conflict_lines = ["=== EXPERT DISAGREEMENTS ==="]
        for sig in conflict_signals:
            if sig.get("conflict"):
                topic = sig["topic"].replace("_", " ").title()
                pos = sig.get("positive_count", 0)
                neg = sig.get("negative_count", 0)
                conflict_lines.append(
                    f"  {topic}: {pos} positive vs {neg} negative signals "
                    f"(agreement {sig['agreement_score']:.0%}) — mention disagreement explicitly"
                )
        if len(conflict_lines) > 1:
            parts.append("\n".join(conflict_lines))

    for i, ev in enumerate(evidence_list, 1):
        tier_tag = f"[AUTHORITY: {ev.authority_tier.upper()}]"
        freshness_tag = f"fresh:{ev.freshness_score:.2f}"
        rank_tag = f"rank:{ev.review_rank_score:.2f}"
        date_tag = f"date:{ev.published_date}" if ev.published_date else ""

        header = f"[SOURCE {i} — {ev.domain} | {tier_tag} | {freshness_tag} | {rank_tag}"
        if date_tag:
            header += f" | {date_tag}"
        header += f" | {ev.source_type}]"

        lines = [header]
        if ev.title:
            lines.append(f"Title: {ev.title[:200]}")

        sr = ev.structured_review
        if sr:
            if sr.get("rating") is not None:
                lines.append(f"Rating: {sr['rating']}/10")
            if sr.get("pros"):
                lines.append("Pros: " + "; ".join(sr["pros"][:5]))
            if sr.get("cons"):
                lines.append("Cons: " + "; ".join(sr["cons"][:5]))
            if sr.get("verdict"):
                lines.append(f"Verdict: {sr['verdict'][:300]}")
            if sr.get("mentioned_price"):
                lines.append(f"Price mentioned: {sr['mentioned_price']}")

        lines.append("---")
        lines.append(ev.raw_content[:8_000])  # preserve raw content, capped

        parts.append("\n".join(lines))

    return "\n\n".join(parts)
