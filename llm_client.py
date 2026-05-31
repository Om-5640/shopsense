"""
Gemini analyzer (v2).

Improvements over v1:
- Separates materials/categories from specific buyable products
- Source-aware: weights review sites and Reddit differently
- Surfaces complaints with confidence levels (not just 3+ rule)
- Subreddit names returned WITHOUT 'r/' prefix (fixes display bug)
- Concise output format to avoid truncation
"""

import os
import json
import logging
import time
import re
import requests
from typing import Any
from dotenv import load_dotenv

_logger = logging.getLogger(__name__)

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
from models import GEMINI_MODEL, gemini_url
GEMINI_URL = gemini_url()

MAX_INPUT_CHARS = 200_000
MAX_OUTPUT_TOKENS = 65_000


def _post_with_retry(url, body, params, max_attempts=3, wait=10):
    last_err = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                params=params,
                json=body,
                timeout=180,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                print(f"[gemini] attempt {attempt + 1} failed ({type(e).__name__}). Retrying in {wait}s...")
                time.sleep(wait)
    raise last_err


def call_gemini(prompt: str, system: str = "", json_mode: bool = False) -> tuple[str, str]:
    """Returns (text, finish_reason)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("Set GEMINI_API_KEY env var. Get one at https://aistudio.google.com/apikey")

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    resp = _post_with_retry(GEMINI_URL, body, {"key": GEMINI_API_KEY})
    data = resp.json()

    try:
        cand = data["candidates"][0]
        finish = cand.get("finishReason", "STOP")
        text = cand["content"]["parts"][0]["text"]
        return text, finish
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response shape: {json.dumps(data)[:500]}") from e


# ---- prompts ----

EXTRACT_SYSTEM = """You are a meticulous shopping research analyst reading Reddit threads AND review articles to extract buying recommendations.

SOURCE WEIGHTING:
- Reddit gives crowd signal: many anecdotes, mixed quality, lots of noise
- Review sites give expert signal: fewer voices but more thorough testing
- A product backed by BOTH sources is the strongest signal
- A product only in reviews may be SEO-pushed - cross-check Reddit
- A product only on Reddit but mentioned by many distinct users is still strong
- Review site authority tiers (shown as [AUTHORITY: X] in sources):
  - TRUSTED: top-tier editorial (Wirecutter, RTINGS, etc.) — weight heavily
  - GOOD: reputable but not authority (Amazon reviews, Medium) — weight moderately
  - UNKNOWN: unverified source — weight lightly, treat like a single Reddit mention

SEPARATION:
- "materials" = categories/types like "cotton blanket", "wool comforter", "bamboo sheets"
- "products" = specific buyable items with brand names like "Buffy Breeze Comforter"
- A user asking "what should I buy" cares about both, but they're different decisions
- Never mix them in the same list
- For each material/category, ALWAYS include 2-3 example_products that fall in that category
  (e.g., "Dive Watches" → example_products: ["Seiko SKX007", "Citizen Promaster Diver"])
- Examples should be specific products mentioned in the research, not generic placeholders

BUDGET FEASIBILITY (critical):
- The user's query includes a budget. ONLY surface products that realistically fit that budget.
- Example: "best watch under ₹5000" → ₹5000 is ~$60 USD. Do NOT include Rolex, Omega, Tudor, Grand Seiko, etc.
  Even if Reddit mentions them, they're irrelevant to a ₹5000 buyer.
- Example: "best earbuds under $50" → exclude AirPods Pro, Sony WF-1000XM5 ($200+).
- If a Reddit thread is clearly about a higher budget and a different user, skip those products.
- When in doubt about a product's price, INCLUDE it only if multiple sources mention it as fitting the user's budget.
- Currency hint: ₹/Rs = Indian rupees (1 USD ≈ 83 INR), £ = GBP (1 USD ≈ 0.78), € = EUR (1 USD ≈ 0.92).

COMPLAINT RULES:
- Surface ALL complaints you find, but label with confidence:
  - "confirmed" = 3+ distinct users mention it
  - "reported" = 2 users mention it
  - "single" = only 1 user (still useful but flag it)
- Don't censor complaints. The user wants to know risks.
- REPLIES MATTER: when a top-level comment praises a product and the replies disagree, that's important counter-signal. Treat replies as separate users with their own opinions.

OTHER:
- Subreddit names: return WITHOUT 'r/' prefix. Just "Bedding" not "r/Bedding".
- Quotes: under 15 words each.
- Ignore obvious marketing/affiliate language.
- Return STRICT JSON only - no fences, no commentary."""


EXTRACT_PROMPT_TEMPLATE = """Researching: "{query}"

Below are {n} sources: a mix of Reddit threads and review articles. Extract recommendations.

Output schema (BE CONCISE - lists max 3 items unless critical):
{{
  "materials": [
    {{
      "name": "Material/category name",
      "mention_count": 0,
      "distinct_recommenders": 0,
      "praise": ["item1", "item2"],
      "complaints": [{{"text": "...", "confidence": "confirmed|reported|single"}}],
      "example_products": ["Brand Model X", "Brand Model Y"],
      "sources": ["reddit:Bedding", "review:wirecutter.com"]
    }}
  ],
  "products": [
    {{
      "name": "Brand Product Name",
      "mention_count": 0,
      "distinct_recommenders": 0,
      "positive_mentions": 0,
      "negative_mentions": 0,
      "praise": ["..."],
      "complaints": [{{"text": "...", "confidence": "confirmed|reported|single"}}],
      "representative_quote": "short quote under 15 words",
      "sources": ["reddit:Bedding", "review:nytimes.com"],
      "signal_strength": "high|medium|low"
    }}
  ],
  "summary": "2-3 sentence overview synthesizing what the data shows (MUST be a single plain string, NOT a JSON object)"
}}

signal_strength rules:
- "high": backed by both Reddit AND review sites, 5+ distinct recommenders
- "medium": one source type with 3+ distinct recommenders
- "low": fewer than 3 distinct recommenders OR only single-source

SOURCES:
{sources_text}
"""


def format_sources_for_prompt(sources: list[dict], char_budget: int) -> str:
    """Flatten unified sources to text. Reddit = thread+comments, reviews = title+content."""
    sections = []
    for i, s in enumerate(sources, 1):
        header = f"\n===== SOURCE {i} ({s['source_type']}) ====="
        # Show authority tier for review sites so analyzer can weight accordingly
        authority = s.get("authority_tier", "")
        authority_tag = f" [AUTHORITY: {authority.upper()}]" if authority and s["source_type"] == "review" else ""
        section = [
            header,
            f"From: {s['source_name']}{authority_tag} | URL: {s['url']}",
            f"Title: {s['title']}",
        ]
        if s.get("body"):
            section.append(f"Content: {s['body']}")
        if s.get("discussions"):
            section.append("Comments (sorted by upvotes, replies indented):")
            for d in s["discussions"]:
                depth = d.get("depth", 0)
                indent = "  " * (depth + 1)
                tag = "" if depth == 0 else f" (reply L{depth})"
                if d.get("controversial"):
                    tag += " [CONTROVERSIAL - mixed opinions]"
                section.append(f"{indent}[+{d['score']}]{tag} {d['text']}")
        sections.append("\n".join(section))

    full = "\n".join(sections)
    if len(full) <= char_budget:
        return full

    # R-03: Warn when sources are truncated so we can diagnose missed data
    _logger.warning(
        "[R03] source text truncated: %d chars → %d chars budget (%d sources)",
        len(full), char_budget, len(sources),
    )

    # Trim each source proportionally
    per_source = char_budget // max(len(sources), 1)
    trimmed = []
    for sec in sections:
        if len(sec) > per_source:
            sec = sec[:per_source] + "\n  [...truncated for length]"
        trimmed.append(sec)
    return "\n".join(trimmed)


def _try_repair_json(raw: str) -> dict:
    """Strip fences + repair truncated/malformed JSON from LLM responses."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Fast path: valid JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # json-repair handles trailing commas, missing quotes, truncation, etc.
    try:
        import json_repair
        result = json_repair.loads(cleaned)
        if isinstance(result, (dict, list)):
            return result
    except Exception:
        pass

    # Last resort: walk backwards to find a valid closing point
    for cut in range(len(cleaned) - 1, max(len(cleaned) - 200, 0), -1):
        candidate = cleaned[:cut].rstrip().rstrip(",")
        for ending in ['"}]}', ']}]}', ']}', '}]}', '}']:
            try:
                return json.loads(candidate + ending)
            except json.JSONDecodeError:
                continue

    return {
        "materials": [],
        "products": [],
        "summary": "(Analysis failed: response was truncated and unrepairable)"
    }


def safe_json_loads(raw: str) -> dict | list:
    """Public alias for _try_repair_json — use this at all LLM call sites."""
    return _try_repair_json(raw)


def analyze_sources(query: str, sources: list[dict]) -> dict:
    """Run analysis with full retry / repair pipeline.

    Primary: Gemini 2.5 Flash (1M context, handles all sources at once)
    Fallback: Groq Llama 3.3 70B (128K context, truncates to fit if needed)
    """
    char_budget = MAX_INPUT_CHARS

    raw = ""
    for attempt in range(3):
        sources_text = format_sources_for_prompt(sources, char_budget)
        prompt = EXTRACT_PROMPT_TEMPLATE.format(
            query=query,
            n=len(sources),
            sources_text=sources_text,
        )
        print(f"[gemini] sending prompt ({len(prompt):,} chars, ~{len(prompt)//4:,} tokens)")

        try:
            raw, finish = call_gemini(prompt, system=EXTRACT_SYSTEM, json_mode=True)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "rate" in err_str:
                print(f"[fallback] Gemini quota/rate hit. Switching to Groq for source analysis.")
            else:
                print(f"[fallback] Gemini failed ({type(e).__name__}). Switching to Groq for source analysis.")
            return _analyze_with_groq_fallback(query, sources)

        if finish == "MAX_TOKENS":
            print(f"[gemini] output truncated. Shrinking input and retrying...")
            char_budget = char_budget // 2
            continue

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[gemini] JSON parse failed: {e}. Attempting repair...")
            return _try_repair_json(raw)

    print("[gemini] all attempts truncated. Repairing final output.")
    return _try_repair_json(raw)


def analyze_with_summaries(query: str, thread_summaries: list[dict], review_pages: list[dict],
                           primary_noun: str = "", preference_hint: str = "") -> dict:
    """
    NEW v5 flow: aggregate pre-summarized thread data (from parallel sub-agents)
    + raw review pages → ranked products.

    Much smaller input than raw flow (~30K vs 150K chars), so:
    - Far less likely to hit MAX_TOKENS truncation
    - Better extraction quality (focused structured input vs noisy raw text)
    - Faster (single small call vs multiple retry attempts)
    """
    from thread_summarizer import format_summaries_for_main_analyzer
    from agents import run_agent

    summaries_text = format_summaries_for_main_analyzer(thread_summaries)

    # Format reviews compactly (these were NOT summarized in parallel, kept as-is)
    # review_fetch.py returns dicts with 'domain' (not 'source_name') and 'content' (not 'body').
    # Fall back gracefully so this works whether called with raw or normalizer-mapped dicts.
    review_text_parts = []
    for r in review_pages:
        authority = r.get("authority_tier", "unknown")
        source_name = r.get("source_name") or r.get("domain", "?")
        content = (r.get("body") or r.get("content") or "")[:6000]
        review_text_parts.append(
            f"\n--- REVIEW SITE: {source_name} [AUTHORITY: {authority.upper()}] ---\n"
            f"Title: {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\n"
            f"Content: {content}"
        )
    reviews_text = "\n".join(review_text_parts)

    # Build strong product-type constraint if we know the primary noun
    noun = primary_noun.strip() if primary_noun else query.split()[0]
    noun_constraint = (
        f"\n\n⚠️  CRITICAL PRODUCT TYPE CONSTRAINT ⚠️\n"
        f"The user is shopping for: **{noun}**\n"
        f"EVERY product in your 'products' list MUST be a {noun}.\n"
        f"If the research mentions other product types (e.g., sunscreens when user asked for facewash,\n"
        f"or chargers when user asked for earbuds), EXCLUDE them entirely.\n"
        f"Do NOT include related products. Only '{noun}' products.\n"
    ) if noun else ""

    user_context = ""
    if preference_hint:
        # Keep compact — just enough for the analyzer to surface relevant products
        hint_truncated = preference_hint[:300].strip()
        user_context = (
            f"\n\n📋 USER PREFERENCES (surface products that fit; flag obvious mismatches):\n"
            f"{hint_truncated}"
        )

    prompt = f"""USER'S QUERY: {query}{noun_constraint}{user_context}

You are aggregating research from multiple sources to recommend products.

PART 1 — REDDIT THREAD SUMMARIES (already pre-extracted by sub-agents):
{summaries_text}

PART 2 — REVIEW SITES (raw content):
{reviews_text}

Apply your system instructions and return the final JSON object with materials, products, and summary."""

    print(f"[main_analyzer] aggregating {len(thread_summaries)} thread summaries + "
          f"{len(review_pages)} review pages ({len(prompt):,} chars total)")

    from analysis_normalizer import normalize_analysis

    raw = ""
    try:
        raw = run_agent("main_analyzer", user_prompt=prompt, system=EXTRACT_SYSTEM)
        parsed = _try_repair_json(raw)
        result = normalize_analysis(parsed)
    except Exception as e:
        print(f"[main_analyzer] failed: {e}. Falling back to legacy raw mode.")
        # Reconstruct sources from summaries for the fallback path
        reconstructed = []
        for s in thread_summaries:
            if s.get("_failed"):
                continue
            reconstructed.append({
                "source_type": "reddit",
                "source_name": f"r/{s.get('subreddit', '?')}",
                "url": s.get("url", ""),
                "title": s.get("thread_summary", "")[:200],
                "body": "",
                "discussions": [
                    {"text": c.get("text", ""), "score": c.get("upvotes", 0), "depth": 0}
                    for c in s.get("top_comments", [])
                ],
                "score": s.get("thread_score", 0),
            })
        reconstructed.extend([
            {**r, "source_type": "review", "source_name": r.get("source_name", "")}
            for r in review_pages
        ])
        result = normalize_analysis(analyze_sources(query, reconstructed))

    # ---- RECOVERY: if products is empty, retry with a stripped-down prompt ----
    # Some LLMs in the fallback chain (especially Mistral free tier) don't honor
    # JSON schema well and embed everything in summary text. A simpler prompt
    # focused only on product extraction often works.
    if not result.get("products"):
        print(f"[main_analyzer] products list empty after normalization.")
        # Log a snippet of what we got back so the user/dev can diagnose
        if raw:
            snippet = raw[:500].replace("\n", " ")
            print(f"[main_analyzer] raw output preview: {snippet}...")

        print(f"[main_analyzer] retrying with simpler product-only extraction prompt...")
        simple_result = _retry_extract_products_only(query, summaries_text, reviews_text)
        if simple_result:
            # Merge: keep original summary/materials, but use rescued products
            result["products"] = simple_result
            print(f"[main_analyzer] recovered {len(simple_result)} products via retry")

    return result


def _retry_extract_products_only(query: str, summaries_text: str, reviews_text: str) -> list[dict]:
    """
    Last-resort recovery: when the main analyzer returned products=[], retry with
    a much simpler prompt focused ONLY on listing product names.

    Stripped down so even less-reliable LLMs in the fallback chain can answer
    correctly. No complex schema, just "give me the product names mentioned."
    """
    from analysis_normalizer import normalize_analysis

    # Build a compact prompt
    snippet = (summaries_text + "\n\n" + reviews_text)[:30000]  # tight budget

    SIMPLE_SYSTEM = """You extract specific buyable product names from research text.

Return ONLY a JSON object with this exact shape:
{
  "products": [
    {"name": "Brand Model Name", "mention_count": 0, "signal_strength": "high|medium|low"}
  ]
}

RULES:
- Only include products with specific brand+model names (e.g. "Realme Buds Air 7", NOT "earbuds")
- mention_count = how many times you saw it mentioned (rough count is fine)
- signal_strength = "high" if praised by many, "medium" if mixed, "low" if mentioned once
- Cap at 15 products
- NO commentary, NO markdown, JSON only"""

    simple_prompt = f"""USER'S QUERY: {query}

RESEARCH TEXT (extract specific product names from this):
{snippet}

List the specific products mentioned (brand + model). Return JSON only."""

    try:
        from agents import run_agent as _run_agent
        raw = _run_agent("main_analyzer", user_prompt=simple_prompt, system=SIMPLE_SYSTEM)
        parsed = _try_repair_json(raw)
        normalized = normalize_analysis(parsed)
        return normalized.get("products", [])
    except Exception as e:
        print(f"[main_analyzer] retry also failed: {e}")
        return []


def _analyze_with_groq_fallback(query: str, sources: list[dict]) -> dict:
    """Run source analysis on Groq Llama 3.3 70B.

    Groq free tier limits:
    - Max 6000 tokens per minute
    - Max 8192 tokens per request
    So we cap input to ~6000 tokens = ~24000 chars aggressively.
    Quality will be lower (fewer sources) but it works.
    """
    from llm_clients import call_groq

    # Groq free tier: 8192 max tokens per request
    # Reserve 2000 for output → 6000 tokens input = ~24000 chars
    GROQ_INPUT_BUDGET = 24_000

    # Only pass top-scored Reddit sources to fit the budget
    # Sort by score so we keep the highest-signal threads
    sorted_sources = sorted(sources, key=lambda s: s.get("score", 0), reverse=True)

    sources_text = format_sources_for_prompt(sorted_sources, GROQ_INPUT_BUDGET)
    prompt = EXTRACT_PROMPT_TEMPLATE.format(
        query=query,
        n=len(sorted_sources),
        sources_text=sources_text,
    )
    print(f"[groq] sending truncated prompt ({len(prompt):,} chars, ~{len(prompt)//4:,} tokens)")

    try:
        raw = call_groq(prompt, system=EXTRACT_SYSTEM, json_mode=True, max_tokens=2048)
        return _try_repair_json(raw)
    except Exception as e:
        print(f"[groq] source analysis failed entirely: {e}")
        return {
            "materials": [],
            "products": [],
            "summary": f"(Both Gemini and Groq failed. Original error: {e})"
        }