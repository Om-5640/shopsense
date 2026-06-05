"""
Targeted evidence enrichment.

After the main pipeline scores products, some high-impact criteria still have no research
evidence (`has_data=False`) — the analyzer simply didn't find that fact in the Reddit/review
corpus. The peer-mean fairness pass keeps the *ranking* fair, but an imputed estimate is not
as good as a real fact. This module fetches the real fact.

Goal: get the most information possible, as accurately as possible, with the fewest API calls.

Strategy (cheap by design):
  1. Only enrich the TOP products (the ones that can realistically be #1 — what platforms act on).
  2. Only the highest-WEIGHT gaps per product (the ones that move the ranking).
  3. ONE Serper search per product ("<product> detailed review specifications"), run in parallel,
     cached 7 days — its snippets typically cover many criteria at once.
  4. ONE batched LLM extraction call across all products+gaps — returns a score only when the
     snippet actually supports it, with the source domain cited. Unsupported gaps stay imputed.

Per uncached search: ≤ MAX_FETCH_PRODUCTS Serper calls + 1 LLM call. Fully wrapped — any failure
returns the input scored list unchanged, so the pipeline never breaks.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import cache
import google_search
from agents import run_agent

# ── Tunables (kept lean to respect free-tier limits) ─────────────────────────
TOP_N_PRODUCTS = 6          # only enrich products that can realistically rank near the top
MAX_GAPS_PER_PRODUCT = 4    # only the highest-weight missing criteria per product
MAX_FETCH_PRODUCTS = 6      # hard Serper-call ceiling per search
_SNIPPETS_PER_PRODUCT = 6   # snippets pulled per product search
_FETCH_WORKERS = 4

# Deep read: pull the TOP result's full page (via Jina Reader) for richer facts than the
# ~30-word Serper snippets. Bounded to one read per product, cached by URL, truncated.
ENABLE_DEEP_FETCH = os.environ.get("ENABLE_DEEP_FETCH", "true").lower() == "true"
_DEEP_CHARS_PER_PRODUCT = 2800   # cap full-page content so the batched prompt stays lean

ENABLE_TARGETED_FETCH = os.environ.get("ENABLE_TARGETED_FETCH", "true").lower() == "true"


EXTRACTION_SYSTEM = """You extract specific product-criterion facts from web search snippets.

You are given several PRODUCTS. For each, a bundle of real search snippets and a list of
CRITERIA we are missing data on. Score ONLY the criteria the snippets actually support.

Return ONLY JSON:
{
  "results": [
    {
      "product": "exact product name as given",
      "criterion": "exact criterion_name as given",
      "score": 0-10,
      "evidence": "short factual justification quoting/paraphrasing the snippet",
      "source": "domain the fact came from, e.g. gsmarena.com"
    }
  ]
}

STRICT RULES:
1. ONLY include a result when a snippet genuinely supports a judgement for that criterion.
   If the snippets say nothing relevant to a criterion, OMIT it — never guess, never invent.
2. score is 0-10: 9-10 excellent, 7-8 good, 5-6 average/mixed, 3-4 weak, 1-2 poor.
3. evidence must be grounded in the snippets — cite the concrete detail (a spec number, a
   tested figure, a clear reviewer verdict). No vague filler.
4. source = the domain of the snippet you used. If unsure, use "web".
5. Use the EXACT product and criterion strings provided. Do not rename them.

NO markdown, JSON only."""


# ── Gap identification ────────────────────────────────────────────────────────

def identify_gaps(scored: list[dict], rubric: dict) -> dict[str, list[dict]]:
    """
    Return {product_name: [{criterion, label, weight}, ...]} for the highest-impact data gaps.
    Only the top products and their highest-weight no-data criteria are included.
    """
    label_by_name = {c["name"]: c.get("label", c["name"]) for c in rubric.get("weighted_criteria", [])}
    weight_by_name = {c["name"]: float(c.get("weight", 0)) for c in rubric.get("weighted_criteria", [])}

    gaps: dict[str, list[dict]] = {}
    for p in scored[:TOP_N_PRODUCTS]:
        name = p.get("name")
        if not name:
            continue
        missing = [
            {"criterion": s["criterion"],
             "label": label_by_name.get(s["criterion"], s["criterion"]),
             "weight": weight_by_name.get(s["criterion"], 0.0)}
            for s in p.get("scores", [])
            if not s.get("has_data")
        ]
        if not missing:
            continue
        # Highest-weight gaps first — those are the ones that actually move the ranking.
        missing.sort(key=lambda g: g["weight"], reverse=True)
        gaps[name] = missing[:MAX_GAPS_PER_PRODUCT]
    return gaps


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _deep_read(url: str) -> str:
    """Full-page read via Jina Reader, cached by URL. Returns '' on any failure."""
    if not url:
        return ""
    ck = f"deepread|{url}"
    hit = cache.get("enrich_deepread", ck)
    if hit is not None:
        return hit
    text = ""
    try:
        from review_fetch import _fetch_via_jina
        content = _fetch_via_jina(url)
        if content:
            text = content[:_DEEP_CHARS_PER_PRODUCT]
    except Exception:
        text = ""
    cache.set("enrich_deepread", ck, text)
    return text


def _fetch_product_evidence(product_name: str, region: str) -> tuple[str, str]:
    """
    One Serper search for a product → (product_name, bundled evidence text).
    Snippets give breadth; the top result's full page (Jina) adds the depth that 30-word
    snippets miss (exact specs, tested figures). Both cached. Falls back to snippets-only.
    """
    region_hint = "" if region in ("", "global") else f" {region}"
    query = f"{product_name} detailed review specifications{region_hint}"
    results = google_search.search(query, num=_SNIPPETS_PER_PRODUCT)

    lines = []
    top_link = ""
    for r in results[:_SNIPPETS_PER_PRODUCT]:
        link = r.get("link", "")
        domain = ""
        try:
            domain = urlparse(link).netloc.replace("www.", "")
        except Exception:
            pass
        snippet = (r.get("snippet") or "").strip()
        title = (r.get("title") or "").strip()
        if snippet or title:
            lines.append(f"[{domain or 'web'}] {title}: {snippet}")
        # Pick the first non-blacklisted-looking real result as the deep-read target.
        if not top_link and link.startswith("http"):
            top_link = link

    # Deep read of the single best result — the part that lifts coverage past snippet-only.
    if ENABLE_DEEP_FETCH and top_link:
        page = _deep_read(top_link)
        if page:
            dom = urlparse(top_link).netloc.replace("www.", "") or "web"
            lines.append(f"\n[FULL PAGE — {dom}]\n{page}")

    return product_name, "\n".join(lines)


def _fetch_all(gaps: dict[str, list[dict]], region: str) -> dict[str, str]:
    """Parallel Serper fetch for each gap product, capped at MAX_FETCH_PRODUCTS."""
    products = list(gaps.keys())[:MAX_FETCH_PRODUCTS]
    evidence: dict[str, str] = {}
    if not products:
        return evidence
    with ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(products))) as pool:
        futures = {pool.submit(_fetch_product_evidence, name, region): name for name in products}
        for fut in as_completed(futures):
            try:
                name, text = fut.result()
                if text:
                    evidence[name] = text
            except Exception:
                continue
    return evidence


# ── Extraction ────────────────────────────────────────────────────────────────

def _extract_gap_scores(gaps: dict[str, list[dict]], evidence: dict[str, str]) -> list[dict]:
    """One batched LLM call → list of {product, criterion, score, evidence, source}."""
    blocks = []
    for name, missing in gaps.items():
        snippets = evidence.get(name)
        if not snippets:
            continue
        crit_lines = "\n".join(f"  - {g['criterion']} ({g['label']})" for g in missing)
        blocks.append(f"PRODUCT: {name}\nMISSING CRITERIA:\n{crit_lines}\nSEARCH SNIPPETS:\n{snippets}")
    if not blocks:
        return []

    prompt = (
        "Extract the missing criterion facts for each product below.\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\nReturn one result per criterion you can support from the snippets."
    )
    try:
        raw = run_agent("evidence_enricher", user_prompt=prompt, system=EXTRACTION_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        out = data.get("results", []) if isinstance(data, dict) else []
        return [r for r in out if isinstance(r, dict) and r.get("product") and r.get("criterion")]
    except Exception:
        return []


# ── Patch ─────────────────────────────────────────────────────────────────────

def _patch_scores(scored: list[dict], extracted: list[dict], gaps: dict[str, list[dict]]) -> int:
    """Write extracted real data into the matching no-data criteria. Returns count patched."""
    valid_gap_keys = {(name, g["criterion"]) for name, gs in gaps.items() for g in gs}
    by_product = {p.get("name"): p for p in scored}
    patched = 0
    for r in extracted:
        name = r.get("product")
        crit = r.get("criterion")
        if (name, crit) not in valid_gap_keys:
            continue  # only fill gaps we asked about — never overwrite real data
        score = r.get("score")
        if not isinstance(score, (int, float)):
            continue
        p = by_product.get(name)
        if not p:
            continue
        for s in p.get("scores", []):
            if s["criterion"] == crit and not s.get("has_data"):
                s["score"] = max(0.0, min(10.0, float(score)))
                src = r.get("source") or "web"
                ev = (r.get("evidence") or "").strip()
                s["evidence"] = f"{ev} (source: {src})" if ev else f"found via targeted search ({src})"
                s["has_data"] = True
                s.pop("imputed", None)
                patched += 1
                break
    return patched


# ── Public entry ──────────────────────────────────────────────────────────────

def enrich_scores(scored: list[dict], rubric: dict, region: str = "global",
                  cancelled_check=None) -> list[dict]:
    """
    Fill the highest-impact data gaps with real, sourced facts, then re-finalize the ranking.
    Returns the input list unchanged on any failure or when disabled — never raises, never breaks
    the pipeline. Re-runs the scorer's fairness pass so percentages/coverage/confidence reflect the
    newly-found real data (remaining gaps stay peer-mean imputed).
    """
    if not ENABLE_TARGETED_FETCH or not scored or not google_search.is_configured():
        return scored
    try:
        gaps = identify_gaps(scored, rubric)
        if not gaps:
            return scored
        if cancelled_check and cancelled_check():
            return scored

        evidence = _fetch_all(gaps, region)
        if not evidence:
            return scored
        if cancelled_check and cancelled_check():
            return scored

        extracted = _extract_gap_scores(gaps, evidence)
        if not extracted:
            return scored

        patched = _patch_scores(scored, extracted, gaps)
        if patched == 0:
            return scored

        # Re-run the fairness pass so totals/coverage/confidence reflect the new real data.
        from scorer import _finalize_scoring
        result = _finalize_scoring(scored, rubric)
        print(f"[enrich] filled {patched} data gap(s) with targeted search across {len(evidence)} product(s)")
        return result
    except Exception as exc:
        print(f"[enrich] non-fatal: {exc}")
        return scored
