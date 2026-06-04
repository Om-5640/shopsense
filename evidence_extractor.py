"""
Criterion evidence extractor — intermediate layer between research and scorer.

Pipeline:
  Research Text → Evidence Extraction → Structured Facts → Scorer

Instead of passing 6000+ chars of raw research to the scoring LLM, this module
pre-extracts per-criterion signal counts and verbatim quotes. The scorer then
receives compact, noise-free evidence instead of raw text.

Typical reduction: 10-30x fewer input tokens to the scoring LLM.
Side effects: fewer hallucinations, more consistent scores, lower latency.
"""

import json
import re
import logging
from agents import run_agent

_logger = logging.getLogger(__name__)


# ── Prompts ────────────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = """Extract product criterion evidence from research text.

For each criterion: count positive/negative signals, collect up to 3 verbatim quotes (max 10 words each).

Return ONLY compact JSON:
{"criterion_name": {"pos": N, "neg": N, "quotes": ["short quote", "..."]}}

Rules:
- pos: count of explicit positive mentions (praised, recommended, works well)
- neg: count of explicit negative mentions (complained about, criticized, failed)
- quotes: exact words from the text, trimmed to 10 words max
- Omit criteria with zero evidence — skip their key entirely
- No inference, no opinions — only what is explicitly stated in the text

JSON only. No markdown."""


_BATCH_EXTRACT_SYSTEM = """Extract criterion evidence from research text for multiple products.

For each product and each criterion: count positive/negative signals, collect up to 3 short verbatim quotes (max 10 words each).

Return ONLY compact JSON:
{
  "Product Name": {
    "criterion_name": {"pos": N, "neg": N, "quotes": ["quote1", "quote2"]}
  }
}

Rules:
- Keep evidence strictly per-product — never mix evidence across products
- pos/neg: explicit positive/negative mentions in that product's research only
- quotes: exact short excerpts, 10 words max, from that product's research only
- Omit criterion key when there is zero evidence for that product+criterion pair
- JSON only. No markdown."""


# ── JSON parser ────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*\n?", re.MULTILINE | re.IGNORECASE)
_CLOSE_FENCE_RE = re.compile(r"\n?```\s*$", re.MULTILINE | re.IGNORECASE)


def _parse_json(raw: str) -> dict:
    """Strip markdown fences, parse JSON. Falls back to brace-extraction. Returns {} on failure."""
    cleaned = _FENCE_RE.sub("", raw.strip())
    cleaned = _CLOSE_FENCE_RE.sub("", cleaned).strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Partial recovery: find outermost {...} block
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            result = json.loads(cleaned[brace_start:brace_end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    _logger.warning("[evidence_extractor] JSON parse failed, raw: %.200s", raw)
    return {}


# ── Evidence coercion ──────────────────────────────────────────────────────────

def _empty_evidence() -> dict:
    """Always returns a fresh dict with its own quotes list (Bug 2 fix — no shared mutable state)."""
    return {"pos": 0, "neg": 0, "quotes": []}


def _coerce_evidence(raw_entry) -> dict:
    """Normalize a raw LLM evidence entry to {pos, neg, quotes}."""
    if not isinstance(raw_entry, dict):
        return _empty_evidence()

    def _safe_count(v) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    quotes = raw_entry.get("quotes", [])
    if not isinstance(quotes, list):
        quotes = []

    return {
        "pos": _safe_count(raw_entry.get("pos", 0)),
        "neg": _safe_count(raw_entry.get("neg", 0)),
        "quotes": [str(q)[:80] for q in quotes[:3] if q],
    }


# ── Single-product extraction ──────────────────────────────────────────────────

def extract_criterion_evidence(
    product_name: str,
    criteria: list[dict],
    research_text: str,
) -> dict:
    """
    Extract structured per-criterion evidence for one product via one LLM call.

    Args:
        product_name : canonical product name
        criteria     : list of {name, label} criterion dicts
        research_text: research text already filtered to this product's mentions

    Returns:
        {criterion_name: {pos: N, neg: N, quotes: [...]}}
        Missing criteria (no evidence found) get empty evidence — never raises.
    """
    if not research_text or not research_text.strip():
        return {c["name"]: _empty_evidence() for c in criteria}

    criteria_lines = "\n".join(f"{c['name']}: {c['label']}" for c in criteria)

    prompt = (
        f"PRODUCT: {product_name}\n\n"
        f"CRITERIA:\n{criteria_lines}\n\n"
        f"<research>\n{research_text[:5000]}\n</research>\n\n"
        "Extract evidence for each criterion above."
    )

    try:
        raw = run_agent("main_analyzer", user_prompt=prompt, system=_EXTRACT_SYSTEM)  # Bug 1 fix
        parsed = _parse_json(raw)
    except Exception as exc:
        _logger.warning("[evidence_extractor] extraction failed for %r: %s", product_name, exc)
        return {c["name"]: _empty_evidence() for c in criteria}

    return {
        c["name"]: _coerce_evidence(parsed.get(c["name"])) if c["name"] in parsed else _empty_evidence()
        for c in criteria
    }


# ── Batch extraction ───────────────────────────────────────────────────────────

def extract_evidence_batch(
    products: list[dict],
    criteria: list[dict],
    research_texts: list[str],
) -> list[dict]:
    """
    Extract criterion evidence for a batch of products in one LLM call.

    Args:
        products      : list of product dicts (must have "name" key)
        criteria      : list of {name, label} criterion dicts (same for all products)
        research_texts: per-product filtered research texts (parallel with products)

    Returns:
        list of evidence dicts, one per product, parallel with input.
        Failed products get all-empty evidence — never raises.
    """
    if not products:
        return []

    empty_all = {c["name"]: _empty_evidence() for c in criteria}
    criteria_lines = "\n".join(f"{c['name']}: {c['label']}" for c in criteria)

    # Distribute character budget proportionally so total stays under ~12K
    per_budget = min(4000, max(400, 12000 // len(products)))

    product_blocks = []
    for p, text in zip(products, research_texts):
        truncated = (text or "")[:per_budget]
        product_blocks.append(
            f"--- PRODUCT: {p.get('name', '?')} ---\n<research>\n{truncated}\n</research>"
        )

    prompt = (
        "PRODUCTS:\n" + "\n\n".join(product_blocks) +
        f"\n\nCRITERIA:\n{criteria_lines}\n\n"
        "Extract evidence per product per criterion."
    )

    try:
        raw = run_agent("main_analyzer", user_prompt=prompt, system=_BATCH_EXTRACT_SYSTEM)  # Bug 1 fix
        parsed = _parse_json(raw)
    except Exception as exc:
        _logger.warning("[evidence_extractor] batch extraction failed: %s", exc)
        return [{c["name"]: _empty_evidence() for c in criteria} for _ in products]

    results: list[dict] = []
    for p in products:
        name = p.get("name", "?")

        # Exact match first, then case-insensitive fallback
        product_evidence = parsed.get(name)
        if product_evidence is None:
            for key, val in parsed.items():
                if key.lower() == name.lower():
                    product_evidence = val
                    break

        if not isinstance(product_evidence, dict):
            _logger.debug("[evidence_extractor] no evidence in batch response for %r", name)
            results.append({c["name"]: _empty_evidence() for c in criteria})
            continue

        results.append({
            c["name"]: _coerce_evidence(product_evidence.get(c["name"])) if c["name"] in product_evidence else _empty_evidence()
            for c in criteria
        })

    return results


# ── Formatter for scorer prompt ────────────────────────────────────────────────

def format_evidence_for_scorer(
    product_name: str,
    evidence: dict,
    rubric: dict,
) -> str:
    """
    Format structured evidence as compact text for the scoring LLM.

    Example output:
        PRODUCT: Sony XM5
        CRITERION EVIDENCE:
          battery_life [Battery Life | wt:8.0]: ✓8 ✗1 | "8-9 hours", "lasted all week"
          comfort [Comfort | wt:6.0]: ✓5 ✗3 | "comfortable", "heavy after hours"
          [NO DATA] value_for_money [Value | wt:5.0]
    """
    lines = [f"PRODUCT: {product_name}", "CRITERION EVIDENCE:"]

    for c in rubric["weighted_criteria"]:
        cname = c["name"]
        label = c["label"]
        weight = c.get("weight", 0)
        ev = evidence.get(cname) or _empty_evidence()

        if ev["pos"] == 0 and ev["neg"] == 0 and not ev["quotes"]:
            lines.append(f"  [NO DATA] {cname} [{label} | wt:{weight}]")
        else:
            quote_part = (
                " | " + ", ".join(f'"{q}"' for q in ev["quotes"])
                if ev["quotes"] else ""
            )
            lines.append(
                f"  {cname} [{label} | wt:{weight}]: "
                f"✓{ev['pos']} ✗{ev['neg']}{quote_part}"
            )

    return "\n".join(lines)
