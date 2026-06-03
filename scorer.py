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

import functools
import json
import logging
import re
import os
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor, as_completed
from agents import run_agent
from llm_clients import GroqQuotaExhausted
from evidence_extractor import (
    extract_evidence_batch,
    extract_criterion_evidence,
    format_evidence_for_scorer,
)

_logger = logging.getLogger(__name__)

# Parallel batch scoring — no per-call sleep needed
MAX_SCORING_WORKERS = 4    # One concurrent call per provider in the pool

# Scoring mode: "llm" (full), "hybrid" (LLM for top 10, fast for rest), "fast" (heuristic only)
_VALID_SCORING_MODES = {"llm", "hybrid", "fast"}
_raw_mode = os.environ.get("SCORING_MODE", "hybrid").lower().strip()
SCORING_MODE = _raw_mode if _raw_mode in _VALID_SCORING_MODES else "hybrid"
if _raw_mode not in _VALID_SCORING_MODES and _raw_mode:
    import logging as _log
    _log.getLogger(__name__).warning(
        "[scorer] SCORING_MODE=%r is not valid (must be llm|hybrid|fast) — defaulting to 'hybrid'", _raw_mode
    )


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
3. If truly no evidence exists, score 4 and write "insufficient data — treat with caution".
4. Reserve 9-10 for strong, multi-source positive evidence.
5. Score 1-3 only for confirmed complaints with multiple users.
6. Be specific in evidence. "Multiple users praise battery" is weak; "Reddit users say 8+ hours on single charge" is good.

NO markdown, NO commentary, JSON only."""


_INJECT_PATTERN = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"system\s*:\s*|you\s+are\s+now|disregard\s+your\s+|"
    r"new\s+instructions?:|override\s+instructions?|"
    r"]\s*}\s*\{|]\s*}\s*SYSTEM)",
    re.IGNORECASE,
)


def _sanitize_research_text(text: str) -> str:
    """
    Strip prompt-injection attempts from Reddit content before it enters LLM prompts.
    Removes instruction-override patterns while preserving genuine product discussion.
    """
    if not text:
        return text
    return _INJECT_PATTERN.sub("[removed]", text)


@functools.lru_cache(maxsize=256)
def _get_token_pattern(token: str) -> re.Pattern:
    """
    Compile a whole-word boundary pattern for a product token.
    Cached so each unique token is compiled exactly once.

    Uses negative lookbehind/lookahead for alphanumeric chars only (NOT hyphens).
    This lets "1000xm5" match inside "wf-1000xm5" while still blocking pure
    substring matches like "xm5" inside "1000xm5" (different alphanumeric context).
    """
    return re.compile(
        r"(?<![a-zA-Z0-9])" + re.escape(token) + r"(?![a-zA-Z0-9])",
        re.IGNORECASE,
    )


def _token_in_text(token: str, text: str) -> bool:
    """True only when `token` appears as a standalone word — not as a fragment of a compound model number."""
    return bool(_get_token_pattern(token).search(text))


def _filter_research_for_product(product_name: str, full_research: str, max_chars: int = 15_000) -> str:
    """
    Find paragraphs that mention this product, plus immediate neighbours for context.

    Model contamination fix: uses whole-word boundary matching so "xm5" does NOT
    match "wh-xm5" or "wf-xm5" — only standalone occurrences count.
    """
    if not full_research:
        return ""

    skip_words = {"the", "and", "for", "pro", "max", "new", "buy", "with"}
    tokens = [
        t.lower() for t in re.findall(r"\w+", product_name)
        if len(t) > 2 and t.lower() not in skip_words
    ]
    if not tokens:
        return full_research[:max_chars]

    # Require all distinctive tokens when there are 2+, to avoid single-brand
    # false matches pulling in unrelated products from the same brand.
    min_matches = min(2, len(tokens))

    paragraphs = re.split(r"\n\s*\n", full_research)

    match_indices: set[int] = set()
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        # Model contamination fix: count only whole-word token matches
        matched = sum(1 for t in tokens if _token_in_text(t, para_lower))
        if matched >= min_matches:
            match_indices.add(i)
            if i > 0:
                match_indices.add(i - 1)
            if i < len(paragraphs) - 1:
                match_indices.add(i + 1)

    if not match_indices:
        return full_research[:max_chars]

    relevant = [paragraphs[i] for i in sorted(match_indices)]
    return "\n\n".join(relevant)[:max_chars]


def _format_criterion_line(c: dict) -> str:
    """Build a single criterion line for scorer prompts. Prefers rationale over description."""
    context = c.get("rationale") or c.get("description") or ""
    return f"- {c['name']}: {c['label']} (weight {c['weight']}/10) — {context}"


def _build_constraint_context(user_intent: dict | None, include_budget: bool = False) -> str:
    """
    Build a compact constraint block injected into scorer prompts.
    Hard constraints and exclusions directly override evidence-based scoring —
    a product violating a MUST/NEVER constraint should score 1-2 on that criterion
    regardless of what Reddit says.

    `include_budget=False` (default): omit budget line since it is already encoded
    in the rubric's price_to_value weight, avoiding triple-injection (ENTROPY-03).
    Set True only for non-scorer callers that don't have a rubric in the same prompt.
    """
    if not user_intent or not isinstance(user_intent, dict):
        return ""
    parts = []
    if user_intent.get("hard_constraints"):
        parts.append("⚠️ HARD CONSTRAINTS — score low (1-3) on the relevant criterion if product violates:")
        for c in user_intent["hard_constraints"][:5]:
            parts.append(f"  MUST: {c}")
    if user_intent.get("exclusions"):
        parts.append("USER EXPLICITLY REJECTS (score relevant criteria 1-3 if product includes these):")
        for e in user_intent["exclusions"][:3]:
            parts.append(f"  ✗ {e}")
    if include_budget and user_intent.get("budget"):
        parts.append(f"Budget constraint: {user_intent['budget']} — penalize value_for_money if product is over budget.")
    return "\n".join(parts) if parts else ""


def score_product(
    product: dict,
    rubric: dict,
    full_research_text: str,
    user_intent: dict | None = None,
) -> dict:
    """
    Score a single product. Returns dict with scores, totals, percentage.

    Pipeline: filter research → extract evidence → compact scoring prompt.
    Falls back to raw research text if evidence extraction fails.
    """
    name = product.get("name", "?")
    criteria = rubric["weighted_criteria"]
    raw_research = _filter_research_for_product(name, full_research_text, max_chars=6000)
    relevant_research = _sanitize_research_text(raw_research)

    constraint_section = _build_constraint_context(user_intent)
    constraint_block = f"\n\n{constraint_section}\n" if constraint_section else ""

    # Try evidence-based path first
    evidence = None
    try:
        compact_criteria = [{"name": c["name"], "label": c["label"]} for c in criteria]
        evidence = extract_criterion_evidence(name, compact_criteria, relevant_research)
    except Exception as exc:
        _logger.debug("[scorer] evidence extraction failed for %r, using raw text: %s", name, exc)

    if evidence is not None:
        evidence_text = format_evidence_for_scorer(name, evidence, rubric)
        prompt = f"{evidence_text}{constraint_block}\nScore each criterion."
        system = EVIDENCE_SYSTEM
    else:
        criteria_text = "\n".join(_format_criterion_line(c) for c in criteria)
        product_text = _format_product(product)
        prompt = (
            f"PRODUCT TO SCORE:\n{product_text}\n\n"
            f"<research_data>\n{relevant_research}\n</research_data>"
            f"{constraint_block}\n"
            f"RUBRIC:\n{criteria_text}\n\n"
            "Score this product against EVERY criterion. Look for implicit evidence too: "
            "'lasted 2 years' implies durability; 'comfortable 8 hours' implies ergonomics."
        )
        system = SYSTEM

    try:
        raw = run_agent("product_scorer", user_prompt=prompt, system=system)
        from llm_client import _try_repair_json
        data = _try_repair_json(raw)
        raw_scores = data.get("scores", [])
    except Exception as e:
        if isinstance(e, GroqQuotaExhausted):
            raise
        print(f"[scorer] failed for {name}: {e}")
        return None

    return _build_scored_dict(product, raw_scores, rubric)


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
    return "\n".join(lines)


# ── Provider-aware token budgeting ───────────────────────────────────────────

_PROVIDER_RESEARCH_BUDGETS: dict[str, int] = {
    "gemini":      6000,   # Gemini 2.0 Flash: 1M token context
    "mistral":     4000,   # Mistral: 32K context
    "openrouter":  4000,
    "groq":        2500,   # Groq LLaMA 70B: 8K token limit per request
    "cerebras":    2500,   # Cerebras: same as Groq
}


def _get_provider_research_budget() -> int:
    """
    Return per-product research character budget based on the first active provider.
    Falls back to the smallest safe budget (Groq/Cerebras) on any error.
    """
    try:
        from agents import get_provider_status
        for provider, info in get_provider_status().items():
            if info.get("session_alive") and not info.get("circuit_blocked"):
                budget = _PROVIDER_RESEARCH_BUDGETS.get(provider, 2500)
                return budget
    except Exception:
        pass
    return 2500


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
2. Score every criterion for every product, even if no evidence (score 4 and write "insufficient data — treat with caution").
3. Look HARD at research text. "Lasted 2 years" implies durability. "Quiet" implies noise score.
4. Evidence: brief, factual, cite source if visible (e.g. "Reddit users praise X" or "rtings.com tested at 32dB").
5. Reserve 9-10 for strong multi-source positive evidence. Reserve 1-3 only for confirmed multi-user complaints.
6. Be consistent: similar evidence should yield similar scores across products.

NO markdown, NO commentary, JSON only."""


# Evidence-based prompts — used when evidence_extractor pre-processed the research.
# Input is compact structured evidence (~300-500 chars) instead of raw text (~6000 chars).

EVIDENCE_SYSTEM = """Score a product against weighted criteria using pre-extracted evidence.

Evidence per criterion: ✓N positive ✗N negative mentions | "verbatim quotes"
[NO DATA] = no research evidence found for this criterion

Return ONLY JSON:
{"scores": [{"criterion": "name", "score": 0-10, "evidence": "brief citation ≤20 words"}]}

Scoring guide (let evidence counts + quote tone drive the number):
9-10: strong ✓ majority (5+), compelling quotes, few or no ✗
7-8:  clear ✓ > ✗, positive quotes present
5-6:  mixed (✓≈✗) or weak signal
4:    [NO DATA] — default when no evidence
3-2:  ✗ > ✓, complaint quotes visible
1:    strong ✗, multiple confirmed failures

Score ALL criteria. EXACT criterion names only. JSON only."""


BATCH_EVIDENCE_SYSTEM = """Score multiple products against weighted criteria using pre-extracted evidence.

Evidence per criterion: ✓N positive ✗N negative mentions | "verbatim quotes"
[NO DATA] = no evidence found

Return ONLY JSON:
{"products": [{"name": "exact name", "scores": [{"criterion": "name", "score": 0-10, "evidence": "≤20 words"}]}]}

Scoring guide: 9-10=strong ✓, 7-8=✓>✗, 5-6=mixed, 4=[NO DATA], 3-2=✗>✓, 1=strong ✗

All criteria. All products. Exact names. JSON only."""


# ── Floating-point precision ───────────────────────────────────────────────────

def _compute_percentage(weighted_total: float, max_possible: float) -> float:
    """
    Decimal-precision percentage — eliminates float accumulation drift that occurs
    when many score×weight products are summed in Python float arithmetic.
    """
    if max_possible <= 0:
        return 0.0
    pct = Decimal(str(weighted_total)) / Decimal(str(max_possible)) * 100
    return float(pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _score_batch(
    products: list[dict],
    rubric: dict,
    full_research_text: str,
    user_intent: dict | None = None,
    per_product_budget: int | None = None,
) -> list[dict]:
    """
    Score a batch of products in a single LLM call.

    Pipeline:
      1. Filter + sanitize research per product
      2. Batch-extract structured evidence via evidence_extractor (one LLM call)
      3. Build compact evidence prompts — ~10x fewer scorer input tokens
      4. Single batch scoring call using structured evidence
      Fallback: raw research text if extraction fails (existing BATCH_SYSTEM path)

    per_product_budget: pre-computed by the caller (score_all_products) so it is not
    recomputed for every batch. Falls back to _get_provider_research_budget() if omitted.

    Returns list of scored dicts. Products that fail get None — caller retries them.
    """
    criteria = rubric["weighted_criteria"]
    if per_product_budget is None:
        per_product_budget = _get_provider_research_budget()

    # Step 1: filter and sanitize research per product
    filtered_research = [
        _sanitize_research_text(
            _filter_research_for_product(p.get("name", ""), full_research_text, max_chars=per_product_budget)
        )
        for p in products
    ]

    # Step 2: batch evidence extraction
    compact_criteria = [{"name": c["name"], "label": c["label"]} for c in criteria]
    evidence_list = None
    try:
        evidence_list = extract_evidence_batch(products, compact_criteria, filtered_research)
    except Exception as exc:
        _logger.debug("[scorer] batch evidence extraction failed, using raw text fallback: %s", exc)

    constraint_section = _build_constraint_context(user_intent)
    constraint_block = f"\n{constraint_section}\n" if constraint_section else ""

    # Step 3 + 4: build prompt and score
    if evidence_list is not None:
        product_parts = [
            f"---\n{format_evidence_for_scorer(p.get('name', '?'), ev, rubric)}"
            for p, ev in zip(products, evidence_list)
        ]
        prompt = (
            "PRODUCTS TO SCORE:\n\n" +
            "\n\n".join(product_parts) +
            f"\n{constraint_block}\n"
            "Score every criterion for every product."
        )
        system = BATCH_EVIDENCE_SYSTEM
    else:
        # Fallback: raw research text (original path)
        criteria_text = "\n".join(_format_criterion_line(c) for c in criteria)
        products_text_parts = []
        for p, rel in zip(products, filtered_research):
            block = [f"--- PRODUCT: {p.get('name', '?')} ---", _format_product(p)]
            if rel:
                block.append(f"\nResearch:\n{rel}")
            products_text_parts.append("\n".join(block))
        prompt = (
            "PRODUCTS TO SCORE (score each against ALL criteria below):\n\n" +
            "\n\n".join(products_text_parts) +
            f"\n{constraint_block}\n"
            f"RUBRIC (apply to every product):\n{criteria_text}\n\n"
            "Score each product against every criterion. Return one entry per product in the 'products' array."
        )
        system = BATCH_SYSTEM

    try:
        raw = run_agent("product_scorer", user_prompt=prompt, system=system)
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
            _logger.debug(
                "[scorer] exact name match failed for %r — LLM returned: %s",
                p.get("name"), list(by_name.keys()),
            )

        if not match or not isinstance(match.get("scores"), list):
            results.append(None)
            continue

        # Convert to full scored format
        scored = _build_scored_dict(p, match["scores"], rubric)
        results.append(scored)

    return results


_COMMUNITY_FIELDS = (
    "mention_count", "distinct_recommenders", "positive_mentions", "negative_mentions",
    "praise", "complaints", "representative_quote", "sources",
    "sentiment_score", "dominant_sentiment", "sentiment_records",
    "cross_subreddit_signal",
)


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
            score = 4.0
            evidence = "insufficient data — treat with caution"

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

    result = {
        "name": product.get("name", "?"),
        "signal_strength": product.get("signal_strength", "?"),
        "scores": final_scores,
        "weighted_total": round(weighted_total, 1),
        "max_possible": round(max_possible, 1),
        "percentage": _compute_percentage(weighted_total, max_possible),
    }
    for field in _COMMUNITY_FIELDS:
        result[field] = product.get(field)
    return result


def score_all_products(
    products: list[dict],
    rubric: dict,
    full_research_text: str,
    progress_callback=None,
    user_intent: dict | None = None,
    cancelled_check=None,
) -> list[dict]:
    """
    Score all products. Mode controlled by SCORING_MODE env var:
      llm    (default) — parallel batch LLM scoring, best quality
      hybrid — LLM for top 10 products, fast heuristic for the rest
      fast   — heuristic only, no LLM calls, ~instant

    user_intent: structured intent dict from interview (hard_constraints, budget, etc.)
                 When provided, constraint violations lower relevant criterion scores.
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

    # ---- hybrid mode: LLM for actual top 10, fast for rest ----
    if SCORING_MODE == "hybrid":
        # Bug fix: pre-sort by fast score so LLM budget goes to the best candidates,
        # not blindly to products[:10] which may not be the highest-scoring ones.
        print(f"[scorer] HYBRID mode: fast pre-scoring {n} products to identify top 10")
        fast_all = [_fast_score(p, rubric, full_research_text) for p in products]
        sorted_by_fast = sorted(
            range(n), key=lambda i: fast_all[i]["weighted_total"], reverse=True
        )
        llm_indices = set(sorted_by_fast[:10])
        llm_products = [products[i] for i in range(n) if i in llm_indices]
        # Products NOT getting LLM treatment keep their fast scores
        fast_keep = [fast_all[i] for i in range(n) if i not in llm_indices]

        print(f"[scorer] HYBRID: LLM scoring top {len(llm_products)}, keeping fast for {len(fast_keep)}")
        llm_scored = _run_parallel_batch_scoring(
            llm_products, rubric, full_research_text, progress_callback, n, user_intent, cancelled_check
        )
        if progress_callback:
            for i, p in enumerate(fast_keep, len(llm_products) + 1):
                progress_callback(i, n, p.get("name", "?"))
        return sorted(llm_scored + fast_keep, key=lambda x: x["weighted_total"], reverse=True)

    # ---- llm mode (default): full parallel batch LLM scoring ----
    print(f"[scorer] LLM mode: parallel batch scoring {n} products, batch={PRODUCTS_PER_BATCH}, workers={MAX_SCORING_WORKERS}")
    return _run_parallel_batch_scoring(products, rubric, full_research_text, progress_callback, n, user_intent, cancelled_check)


def _run_parallel_batch_scoring(
    products: list[dict],
    rubric: dict,
    full_research_text: str,
    progress_callback,
    total_n: int,
    user_intent: dict | None = None,
    cancelled_check=None,
) -> list[dict]:
    """Inner parallel batch executor. Extracted so hybrid mode can call it for a subset."""
    n = len(products)
    print(f"[scorer] parallel batch scoring: {n} products, batch={PRODUCTS_PER_BATCH}, workers={MAX_SCORING_WORKERS}")
    batches = [products[i:i + PRODUCTS_PER_BATCH] for i in range(0, n, PRODUCTS_PER_BATCH)]
    print(f"[scorer] {len(batches)} batches to process")

    # Compute provider budget once — same for all batches in this scoring run.
    # Previously called inside _score_batch (once per batch = 5 provider-status lookups per search).
    _budget = _get_provider_research_budget()

    # Thread-safe results dict: product name → scored dict
    results: dict[str, dict] = {}

    def score_batch_with_retry(batch: list[dict]) -> list[dict]:
        """Try batch scoring; fall back to per-product if batch parse fails."""
        batch_results = _score_batch(batch, rubric, full_research_text, user_intent, per_product_budget=_budget)
        # For any None results (parse failures), retry individually
        final = []
        for p, br in zip(batch, batch_results):
            if br is not None:
                final.append(br)
            else:
                print(f"  [scorer] batch miss for {p.get('name','?')}, retrying individually")
                try:
                    single = score_product(p, rubric, full_research_text, user_intent)
                    final.append(single if single is not None else _default_score(p, rubric))
                except Exception as e:
                    print(f"  [scorer] single retry failed for {p.get('name','?')}: {e}")
                    final.append(_default_score(p, rubric))
        return final

    with ThreadPoolExecutor(max_workers=MAX_SCORING_WORKERS, thread_name_prefix="scorer") as ex:
        future_to_batch = {ex.submit(score_batch_with_retry, batch): batch for batch in batches}

        for future in as_completed(future_to_batch):
            # Check cancellation between batch completions — stops scoring when user hits Stop
            if cancelled_check and cancelled_check():
                ex.shutdown(wait=False, cancel_futures=True)
                break

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
            if s["criterion"] not in new_weights:
                # Drop criteria that no longer exist in the updated rubric.
                # Previously these kept their old weight, inflating totals when the rubric
                # was narrowed (e.g., user removed a criterion via the UI).
                continue
            weight = new_weights[s["criterion"]]
            weighted_total += s["score"] * weight
            max_possible += 10 * weight
            new_scores.append({
                **s,
                "weight": weight,
                "weighted_contribution": round(s["score"] * weight, 1),
            })

        rescored.append({
            **p,
            "scores": new_scores,
            "weighted_total": round(weighted_total, 1),
            "max_possible": round(max_possible, 1),
            "percentage": _compute_percentage(weighted_total, max_possible),
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