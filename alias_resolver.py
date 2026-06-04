"""
Alias resolver — Phase 1 of the precise mention counting pipeline.

For each raw Reddit thread, discovers every way a product is referred to:
abbreviations, nicknames, anaphoric references ("those buds", "the realme").

Two-step workflow:
  coref_pass(thread, llm_client)       → per-thread alias map
  merge_into_registry(all_corefs, ...) → unified ProductInfo registry

The registry is then consumed by mention_counter.build_automaton().
"""

import json
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ProductInfo:
    canonical_name: str
    aliases: list = field(default_factory=list)
    excludes: list = field(default_factory=list)   # terms that cancel a match if present nearby

    def add_alias(self, alias: str) -> None:
        """Add alias case-insensitively, no duplicates."""
        norm = alias.strip()
        if not norm:
            return
        if norm.lower() not in {a.lower() for a in self.aliases}:
            self.aliases.append(norm)

    def add_exclude(self, term: str) -> None:
        """Add exclusion term, no duplicates."""
        norm = term.strip()
        if not norm:
            return
        if norm.lower() not in {e.lower() for e in self.excludes}:
            self.excludes.append(norm)


# ── LLM system prompt (exact as specified) ────────────────────────────────────

COREF_SYSTEM = """You are a product entity resolver for a shopping research agent.
Read this Reddit thread. Find every product mentioned.
For each product, list every way people referred to it in THIS thread:
abbreviations, nicknames, informal names, anaphoric references like
"those buds", "the realme", "it" or "them" when clearly one product.

Respond ONLY with valid JSON. No markdown, no explanation, no backticks.
{
  "Realme Buds Air 7": ["RBA7", "realme buds 7", "those buds"],
  "Sony WF-1000XM5": ["sony xm5", "xm5"]
}

Rules:
- Canonical name: most complete formal name you see in the thread.
- NEVER merge different products. Air 7 and Air 7 Pro are different products.
- Only include aliases actually seen in this thread.
- No products mentioned? Return {}."""


# ── Thread text builder ───────────────────────────────────────────────────────

def _build_thread_text(thread: dict, max_words: int = 6000) -> str:
    """
    Flatten title + body + comments into a single text block capped at max_words.
    Strips markdown code fences and excessive whitespace before counting.
    """
    parts = []

    title = (thread.get("title") or "").strip()
    if title:
        parts.append(f"TITLE: {title}")

    body = (thread.get("body") or "").strip()
    if body:
        parts.append(f"POST: {body}")

    for comment in thread.get("comments", []):
        ctext = (comment.get("body") or "").strip()
        if ctext:
            depth = comment.get("depth", 0)
            indent = "  " * depth
            parts.append(f"{indent}COMMENT: {ctext}")

    full = "\n".join(parts)

    # Strip markdown fences that could confuse the LLM
    full = re.sub(r"```[a-z]*\n?", "", full)
    full = re.sub(r"```", "", full)

    # Truncate to max_words
    words = full.split()
    if len(words) > max_words:
        full = " ".join(words[:max_words])

    return full


# ── JSON extractor ────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    """
    Strip any markdown fences and parse JSON.
    Returns {} on any failure — never raises.
    """
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # Fast path
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError:
        pass

    # Walk backwards to find a parseable truncation.
    # Try multiple closing suffixes — the truncation may be inside an array or string.
    for cut in range(len(cleaned) - 1, max(len(cleaned) - 200, 0), -1):
        candidate = cleaned[:cut].rstrip().rstrip(",")
        for suffix in ("}", ']}', '"]}', '"]}'  ):
            try:
                result = json.loads(candidate + suffix)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue

    return {}


# ── Core functions ────────────────────────────────────────────────────────────

def coref_pass(thread: dict, llm_client) -> dict[str, list[str]]:
    """
    Run one LLM coreference-resolution pass over a single Reddit thread.

    Args:
        thread     : raw Reddit thread dict with keys: title, body, comments
        llm_client : callable matching run_agent(agent_name, user_prompt, system)

    Returns:
        { "Canonical Product Name": ["alias1", "alias2", ...] }
        Returns {} on ANY failure — never raises.
    """
    thread_url = thread.get("url", "?")

    try:
        thread_text = _build_thread_text(thread, max_words=6000)
        if not thread_text.strip():
            return {}

        prompt = (
            f"REDDIT THREAD (subreddit: r/{thread.get('subreddit', '?')}):\n\n"
            f"{thread_text}\n\n"
            f"List every product and all its aliases found in this thread."
        )

        raw = llm_client("thread_summarizer", user_prompt=prompt, system=COREF_SYSTEM)
        result = _extract_json(raw)

        # Validate + sanitize: keys must be non-empty strings, values must be lists of strings
        clean: dict[str, list[str]] = {}
        for canonical, aliases in result.items():
            canonical = str(canonical).strip()
            if not canonical:
                continue
            alias_list = []
            if isinstance(aliases, list):
                for a in aliases:
                    a_str = str(a).strip()
                    if a_str and a_str.lower() != canonical.lower():
                        alias_list.append(a_str)
            clean[canonical] = alias_list

        return clean

    except Exception as exc:
        logger.warning("[alias_resolver] coref_pass failed for %s: %s", thread_url, exc)
        return {}


def merge_into_registry(
    per_thread_corefs: list[dict[str, list[str]]],
    base: dict[str, "ProductInfo"] | None = None,
) -> dict[str, "ProductInfo"]:
    """
    Merge per-thread coref outputs into a unified registry keyed by lowercase canonical name.

    Auto-exclusion rule:
      If both "Widget X" and "Widget X Pro" appear in the registry, add "Widget X Pro"
      to the excludes list of "Widget X" so an "X" match adjacent to "Pro" is cancelled.
      This is one-directional: "Widget X" does NOT go into "Widget X Pro".excludes.

    Args:
        per_thread_corefs : list of dicts returned by coref_pass (one per thread)
        base              : optional existing registry to seed/merge into

    Returns:
        { lower_canonical: ProductInfo }
    """
    registry: dict[str, ProductInfo] = {}

    # Seed from base if provided
    if base:
        for key, info in base.items():
            registry[key.lower()] = info

    for coref_map in per_thread_corefs:
        if not coref_map:
            continue

        for canonical, aliases in coref_map.items():
            key = canonical.lower().strip()
            if not key:
                continue

            if key not in registry:
                registry[key] = ProductInfo(canonical_name=canonical)
            else:
                # Prefer the longer/more formal canonical name seen later
                if len(canonical) > len(registry[key].canonical_name):
                    registry[key].canonical_name = canonical

            for alias in aliases:
                registry[key].add_alias(alias)

    # ── Auto-exclusion pass ───────────────────────────────────────────────────
    # For every pair (base, variant) where variant = base + something extra
    # (e.g., "realme buds air 7" and "realme buds air 7 pro"):
    #   add variant's canonical_name to base.excludes
    # This prevents "Buds Air 7" text from counting as "Buds Air 7 Pro" or vice versa.

    keys = list(registry.keys())
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            # Check if one is a prefix of the other (with a word boundary)
            if key_b.startswith(key_a + " ") or key_b.startswith(key_a + "-"):
                # key_a is the base, key_b is the variant with extra suffix
                # Add key_b's canonical name to key_a's excludes
                registry[key_a].add_exclude(registry[key_b].canonical_name)
                # Also add key_b as exclusion term for key_a
                registry[key_a].add_exclude(key_b)
            elif key_a.startswith(key_b + " ") or key_a.startswith(key_b + "-"):
                # key_b is the base, key_a is the variant with extra suffix
                registry[key_b].add_exclude(registry[key_a].canonical_name)
                registry[key_b].add_exclude(key_a)

    return registry
