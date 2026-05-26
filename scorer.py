"""
Per-product scoring.

For each product surfaced by the research layer, score it 0-10 against each
weighted criterion. Cite evidence from the research data for every score.

Returns products sorted by weighted total score.

Improvements:
- Receives FULL research text (Reddit comments + review excerpts), not just summaries
- Rate-limits to avoid Gemini free tier 429s (6s between calls = 10 req/min)
- Retries failed products at the end of the batch
- Smartly filters research text to only mentions of the product being scored
"""

import json
import time
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from agents import run_agent
from llm_clients import GroqQuotaExhausted

# Parallel batch scoring — no per-call sleep needed
PRODUCTS_PER_BATCH = 4     # 4 products × 2500 chars each ≈ fits any provider's context
MAX_SCORING_WORKERS = 4    # One concurrent call per provider in the pool

# Scoring mode: "llm" (full), "hybrid" (LLM for top 10, fast for rest), "fast" (heuristic only)
SCORING_MODE = os.environ.get("SCORING_MODE", "llm").lower()


SYSTEM = """You score products against a weighted rubric using REAL evidence from research data.

For each criterion, give a 0-10 score with SHORT evidence citing actual data (quotes or specific observations from the research).

Return ONLY a JSON object:
{
  "scores": [
    {
      "criterion": "snake_case_name",
      "score": 0-10,
      "evidence": "short citation (under 25 words)"
    }
  ]
}

RULES:
1. Use the EXACT criterion names given. Don't invent new ones.
2. Look HARD at the research text before saying "no data found". Many criteria have implicit evidence (e.g. "lasted 2 years" implies durability).
3. If truly no evidence exists, score 5 and write "no direct data found".
4. Reserve 9-10 for strong, multi-source positive evidence.
5. Score 1-3 only for confirmed complaints with multiple users.
6. Be specific in evidence. "Multiple users praise battery" is weak; "Reddit users say 8+ hours on single charge" is good.

NO markdown, NO commentary, JSON only."""


def _filter_research_for_product(product_name: str, full_research: str, max_chars: int = 15_000) -> str:
    """
    Find paragraphs in research text that mention this product, PLUS adjacent paragraphs
    for context (replies often follow recommendations and contain key counter-signal).

    Returns a richer context window than before:
    - Default 15K chars (was 8K)
    - Includes paragraph before AND after each match (catches reply context)
    - Multi-token matching: requires at least 1 distinctive token from product name
    """
    if not full_research:
        return ""

    # Split product name into distinctive tokens (skip generic words)
    skip_words = {"the", "and", "for", "pro", "max", "new", "buy", "with"}
    tokens = [
        t.lower() for t in re.findall(r"\w+", product_name)
        if len(t) > 2 and t.lower() not in skip_words
    ]
    if not tokens:
        return full_research[:max_chars]

    paragraphs = re.split(r"\n\s*\n", full_research)

    # Find indices of paragraphs matching the product
    match_indices = set()
    for i, p in enumerate(paragraphs):
        p_lower = p.lower()
        if any(t in p_lower for t in tokens):
            match_indices.add(i)
            # Include surrounding paragraphs for context
            if i > 0:
                match_indices.add(i - 1)
            if i < len(paragraphs) - 1:
                match_indices.add(i + 1)

    if not match_indices:
        return full_research[:max_chars]

    # Build output preserving original paragraph order
    relevant = [paragraphs[i] for i in sorted(match_indices)]
    filtered = "\n\n".join(relevant)
    return filtered[:max_chars]


def score_product(product: dict, rubric: dict, full_research_text: str) -> dict:
    """Score a single product. Returns dict with scores, totals, percentage."""
    criteria_text = "\n".join(
        f"- {c['name']}: {c['label']} (weight {c['weight']}/10) - {c.get('description', '')}"
        for c in rubric["weighted_criteria"]
    )

    product_text = _format_product(product)
    # 6K chars per product is safe for Groq 8K token limit when combined with rubric + system
    relevant_research = _filter_research_for_product(product.get("name", ""), full_research_text, max_chars=6000)

    prompt = f"""PRODUCT TO SCORE:
{product_text}

RELEVANT RESEARCH (Reddit comments + review excerpts mentioning this product):
{relevant_research}

RUBRIC:
{criteria_text}

Score this product against EVERY criterion above. Use the research text to find specific evidence.
For each criterion, look for relevant phrases in the research even if not explicitly labeled.
Example: "lasted 2 years" implies durability; "comfortable for 8 hours" implies ergonomics."""

    try:
        raw = run_agent("product_scorer", user_prompt=prompt, system=SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        raw_scores = data.get("scores", [])
    except Exception as e:
        if isinstance(e, GroqQuotaExhausted):
            raise
        print(f"[scorer] failed for {product.get('name')}: {e}")
        return None

    # Build final scores
    by_name = {s.get("criterion"): s for s in raw_scores if isinstance(s, dict)}
    final_scores = []
    weighted_total = 0.0
    max_possible = 0.0

    for c in rubric["weighted_criteria"]:
        s = by_name.get(c["name"])
        if s and isinstance(s.get("score"), (int, float)):
            score = max(0, min(10, float(s["score"])))
            evidence = s.get("evidence", "")
        else:
            score = 5.0
            evidence = "no direct data found"

        weight = c["weight"]
        weighted_total += score * weight
        max_possible += 10 * weight

        final_scores.append({
            "criterion": c["name"],
            "label": c["label"],
            "weight": weight,
            "score": score,
            "evidence": evidence,
            "weighted_contribution": round(score * weight, 1),
        })

    pct = (weighted_total / max_possible * 100) if max_possible > 0 else 0

    return {
        "name": product.get("name", "?"),
        "signal_strength": product.get("signal_strength", "?"),
        "scores": final_scores,
        "weighted_total": round(weighted_total, 1),
        "max_possible": round(max_possible, 1),
        "percentage": round(pct, 1),
    }


def _format_product(p: dict) -> str:
    """Compact product summary for prompt header."""
    lines = [f"Name: {p.get('name', '?')}"]
    if p.get("mention_count") is not None:
        lines.append(f"Mentions: {p.get('mention_count')} "
                     f"({p.get('positive_mentions', '?')} pos, "
                     f"{p.get('negative_mentions', '?')} neg)")
    if p.get("praise"):
        lines.append(f"Praise (extracted): {', '.join(p['praise'][:5])}")
    if p.get("complaints"):
        comps = [f"{c.get('text', '')} [{c.get('confidence', '?')}]" for c in p["complaints"][:5]]
        lines.append(f"Complaints (extracted): {'; '.join(comps)}")
    if p.get("representative_quote"):
        lines.append(f"Top quote: \"{p['representative_quote']}\"")
    if p.get("sources"):
        lines.append(f"Sources: {', '.join(p['sources'][:5])}")
    return "\n".join(lines)


# Batching: score N products per Groq call to reduce request count
PRODUCTS_PER_BATCH = 3


BATCH_SYSTEM = """You score MULTIPLE products against a weighted rubric using REAL evidence from research data.

For each product, give a 0-10 score per criterion with SHORT evidence citing actual data.

Return ONLY a JSON object:
{
  "products": [
    {
      "name": "exact product name as given",
      "scores": [
        {"criterion": "snake_case_name", "score": 0-10, "evidence": "short citation under 25 words"}
      ]
    }
  ]
}

RULES:
1. Use EXACT product names and EXACT criterion names from the input. Never invent.
2. Score every criterion for every product, even if "no direct data found" (score 5 in that case).
3. Look HARD at research text. "Lasted 2 years" implies durability. "Quiet" implies noise score.
4. Evidence: brief, factual, cite source if visible (e.g. "Reddit users praise X" or "rtings.com tested at 32dB").
5. Reserve 9-10 for strong multi-source positive evidence. Reserve 1-3 only for confirmed multi-user complaints.
6. Be consistent: similar evidence should yield similar scores across products.

NO markdown, NO commentary, JSON only."""


def _score_batch(products: list[dict], rubric: dict, full_research_text: str) -> list[dict]:
    """
    Score a batch of products in a single LLM call.
    Returns list of scored dicts. Products that fail extraction get None — caller retries them.
    """
    criteria_text = "\n".join(
        f"- {c['name']}: {c['label']} (weight {c['weight']}/10) - {c.get('description', '')}"
        for c in rubric["weighted_criteria"]
    )

    # Build prompt with all products and filtered research for each
    # Groq has 8K token limit per request → very tight budget
    # Per-product research: 2500 chars (~625 tokens) × 3 products = 7500 chars
    # Plus rubric + system prompt = ~10K total = ~2500 tokens. Fits comfortably.
    products_text_parts = []
    for p in products:
        prod_block = [f"--- PRODUCT: {p.get('name', '?')} ---"]
        prod_block.append(_format_product(p))
        # Tight context window per product to stay under Groq's 8K limit
        rel = _filter_research_for_product(p.get("name", ""), full_research_text, max_chars=2500)
        if rel:
            prod_block.append(f"\nResearch:\n{rel}")
        products_text_parts.append("\n".join(prod_block))

    products_text = "\n\n".join(products_text_parts)

    prompt = f"""PRODUCTS TO SCORE (score each against ALL criteria below):

{products_text}

RUBRIC (apply to every product):
{criteria_text}

Score each product against every criterion. Return one entry per product in the 'products' array."""

    try:
        raw = run_agent("product_scorer", user_prompt=prompt, system=BATCH_SYSTEM)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        raw_products = data.get("products", []) if isinstance(data, dict) else []
    except Exception as e:
        print(f"[scorer] batch failed: {e}")
        return [None] * len(products)

    # Match LLM outputs back to input products (by name)
    by_name = {}
    for entry in raw_products:
        if isinstance(entry, dict) and entry.get("name"):
            by_name[entry["name"].lower().strip()] = entry

    results = []
    for p in products:
        name_lower = p.get("name", "").lower().strip()
        match = by_name.get(name_lower)
        if not match:
            # Try fuzzy match: any output name containing input name or vice versa
            for out_name, entry in by_name.items():
                if name_lower in out_name or out_name in name_lower:
                    match = entry
                    break

        if not match or not isinstance(match.get("scores"), list):
            results.append(None)
            continue

        # Convert to full scored format
        scored = _build_scored_dict(p, match["scores"], rubric)
        results.append(scored)

    return results


def _build_scored_dict(product: dict, raw_scores: list, rubric: dict) -> dict:
    """Build final scored product dict from raw LLM scores. Shared by batch and single."""
    by_name = {s.get("criterion"): s for s in raw_scores if isinstance(s, dict)}
    final_scores = []
    weighted_total = 0.0
    max_possible = 0.0

    for c in rubric["weighted_criteria"]:
        s = by_name.get(c["name"])
        if s and isinstance(s.get("score"), (int, float)):
            score = max(0, min(10, float(s["score"])))
            evidence = s.get("evidence", "")
        else:
            score = 5.0
            evidence = "no direct data found"

        weight = c["weight"]
        weighted_total += score * weight
        max_possible += 10 * weight

        final_scores.append({
            "criterion": c["name"],
            "label": c["label"],
            "weight": weight,
            "score": score,
            "evidence": evidence,
            "weighted_contribution": round(score * weight, 1),
        })

    pct = (weighted_total / max_possible * 100) if max_possible > 0 else 0
    return {
        "name": product.get("name", "?"),
        "signal_strength": product.get("signal_strength", "?"),
        "scores": final_scores,
        "weighted_total": round(weighted_total, 1),
        "max_possible": round(max_possible, 1),
        "percentage": round(pct, 1),
    }


def score_all_products(
    products: list[dict],
    rubric: dict,
    full_research_text: str,
    progress_callback=None,
) -> list[dict]:
    """
    Score all products. Mode controlled by SCORING_MODE env var:
      llm    (default) — parallel batch LLM scoring, best quality
      hybrid — LLM for top 10 products, fast heuristic for the rest
      fast   — heuristic only, no LLM calls, ~instant
    """
    n = len(products)

    # ---- fast mode: pure heuristic, no LLM ----
    if SCORING_MODE == "fast":
        print(f"[scorer] FAST mode: heuristic scoring {n} products (no LLM)")
        scored = [_fast_score(p, rubric, full_research_text) for p in products]
        if progress_callback:
            for i, p in enumerate(products, 1):
                progress_callback(i, n, p.get("name", "?"))
        return sorted(scored, key=lambda x: x["weighted_total"], reverse=True)

    # ---- hybrid mode: LLM for top 10, fast for rest ----
    if SCORING_MODE == "hybrid":
        llm_products = products[:10]
        fast_products = products[10:]
        print(f"[scorer] HYBRID mode: LLM for {len(llm_products)}, fast for {len(fast_products)}")
        llm_scored = _run_parallel_batch_scoring(llm_products, rubric, full_research_text, progress_callback, n)
        fast_scored = [_fast_score(p, rubric, full_research_text) for p in fast_products]
        if progress_callback:
            for i, p in enumerate(fast_products, len(llm_products) + 1):
                progress_callback(i, n, p.get("name", "?"))
        return sorted(llm_scored + fast_scored, key=lambda x: x["weighted_total"], reverse=True)

    # ---- llm mode (default): full parallel batch LLM scoring ----
    print(f"[scorer] LLM mode: parallel batch scoring {n} products, batch={PRODUCTS_PER_BATCH}, workers={MAX_SCORING_WORKERS}")
    return _run_parallel_batch_scoring(products, rubric, full_research_text, progress_callback, n)


def _run_parallel_batch_scoring(
    products: list[dict],
    rubric: dict,
    full_research_text: str,
    progress_callback,
    total_n: int,
) -> list[dict]:
    """Inner parallel batch executor. Extracted so hybrid mode can call it for a subset."""
    n = len(products)
    print(f"[scorer] parallel batch scoring: {n} products, batch={PRODUCTS_PER_BATCH}, workers={MAX_SCORING_WORKERS}")
    batches = [products[i:i + PRODUCTS_PER_BATCH] for i in range(0, n, PRODUCTS_PER_BATCH)]
    print(f"[scorer] {len(batches)} batches to process")

    # Thread-safe results dict: product name → scored dict
    results: dict[str, dict] = {}

    def score_batch_with_retry(batch: list[dict]) -> list[dict]:
        """Try batch scoring; fall back to per-product if batch parse fails."""
        batch_results = _score_batch(batch, rubric, full_research_text)
        # For any None results (parse failures), retry individually
        final = []
        for p, br in zip(batch, batch_results):
            if br is not None:
                final.append(br)
            else:
                print(f"  [scorer] batch miss for {p.get('name','?')}, retrying individually")
                try:
                    single = score_product(p, rubric, full_research_text)
                    final.append(single if single is not None else _default_score(p, rubric))
                except Exception as e:
                    print(f"  [scorer] single retry failed for {p.get('name','?')}: {e}")
                    final.append(_default_score(p, rubric))
        return final

    with ThreadPoolExecutor(max_workers=MAX_SCORING_WORKERS, thread_name_prefix="scorer") as ex:
        future_to_batch = {ex.submit(score_batch_with_retry, batch): batch for batch in batches}

        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_scored = future.result()
                for p, r in zip(batch, batch_scored):
                    results[p.get("name", "?")] = r
            except GroqQuotaExhausted as e:
                print(f"\n[scorer] quota exhausted: {e}")
                for p in batch:
                    results[p.get("name", "?")] = _default_score(p, rubric)
            except Exception as e:
                print(f"[scorer] batch exception: {type(e).__name__}: {e}")
                for p in batch:
                    results[p.get("name", "?")] = _default_score(p, rubric)

            # Progress callback: report against total_n (used by hybrid mode)
            nonlocal_completed = len(results)
            if progress_callback:
                for p in batch:
                    progress_callback(nonlocal_completed, total_n, p.get("name", "?"))

    # Reconstruct in original order, defaulting any that are still missing
    scored = [results.get(p.get("name", "?"), _default_score(p, rubric)) for p in products]
    print(f"\n[scorer] done: {len([s for s in scored if s])} products scored")
    return sorted(scored, key=lambda x: x["weighted_total"], reverse=True)


def _fast_score(product: dict, rubric: dict, full_research_text: str) -> dict:
    """
    Heuristic scoring without LLM calls.
    Uses mention count, positive/negative ratio, and signal_strength as proxy.
    ~100x faster than LLM scoring; quality is lower but good for quick previews.
    """
    name = product.get("name", "?")
    mentions = int(product.get("mention_count", 0) or 0)
    pos = int(product.get("positive_mentions", 0) or 0)
    neg = int(product.get("negative_mentions", 0) or 0)
    signal = (product.get("signal_strength") or "").lower()

    # Base sentiment score from positive/negative ratio
    if pos + neg > 0:
        sentiment_score = (pos / (pos + neg)) * 10
    else:
        sentiment_score = 5.0

    # Mention volume boost (more mentions = more data = more confidence)
    if mentions >= 20:
        volume_bonus = 1.0
    elif mentions >= 10:
        volume_bonus = 0.5
    elif mentions >= 5:
        volume_bonus = 0.2
    else:
        volume_bonus = -0.5

    # Signal strength modifier
    signal_mod = {"strong": 0.5, "moderate": 0.0, "weak": -0.5}.get(signal, 0.0)

    base = max(1.0, min(9.5, sentiment_score + volume_bonus + signal_mod))

    raw_scores = []
    for c in rubric["weighted_criteria"]:
        raw_scores.append({
            "criterion": c["name"],
            "score": round(base, 1),
            "evidence": f"heuristic ({mentions} mentions, {pos}+ / {neg}-)",
        })

    result = _build_scored_dict(product, raw_scores, rubric)
    result["signal_strength"] = product.get("signal_strength", "?")
    result["_fast_scored"] = True
    return result


def _default_score(product: dict, rubric: dict) -> dict:
    """Build a scored dict with all-5 scores when LLM is unavailable.
    Better than dropping the product entirely — user still sees it ranked, just neutrally."""
    raw_scores = [
        {"criterion": c["name"], "score": 5, "evidence": "(LLM unavailable - default score)"}
        for c in rubric["weighted_criteria"]
    ]
    result = _build_scored_dict(product, raw_scores, rubric)
    result["signal_strength"] = product.get("signal_strength", "?")
    return result


def recompute_with_new_weights(scored_products: list[dict], new_rubric: dict) -> list[dict]:
    """Pure Python re-ranking after user adjusts weights. No new LLM calls."""
    new_weights = {c["name"]: c["weight"] for c in new_rubric["weighted_criteria"]}
    rescored = []
    for p in scored_products:
        weighted_total = 0.0
        max_possible = 0.0
        new_scores = []
        for s in p["scores"]:
            weight = new_weights.get(s["criterion"], s["weight"])
            weighted_total += s["score"] * weight
            max_possible += 10 * weight
            new_scores.append({
                **s,
                "weight": weight,
                "weighted_contribution": round(s["score"] * weight, 1),
            })

        pct = (weighted_total / max_possible * 100) if max_possible > 0 else 0
        rescored.append({
            **p,
            "scores": new_scores,
            "weighted_total": round(weighted_total, 1),
            "max_possible": round(max_possible, 1),
            "percentage": round(pct, 1),
        })

    return sorted(rescored, key=lambda x: x["weighted_total"], reverse=True)


def display_results(scored_products: list[dict], top_n: int = 5) -> None:
    print(f"\n{'='*72}")
    print(f"  PERSONALIZED RANKING")
    print(f"{'='*72}\n")

    for i, p in enumerate(scored_products[:top_n], 1):
        pct = p["percentage"]
        bar_len = int(pct / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"{i}. {p['name']}  [{p.get('signal_strength', '?').upper()} signal]")
        print(f"   Score: {p['weighted_total']}/{p['max_possible']} ({pct}%)  [{bar}]")
        print(f"   How it scored:")

        sorted_scores = sorted(p["scores"], key=lambda s: s["weighted_contribution"], reverse=True)
        for s in sorted_scores:
            score_str = f"{s['score']:.0f}/10"
            print(f"     {s['label']:30} {score_str:6} (×{s['weight']:>2}) — {s['evidence']}")
        print()