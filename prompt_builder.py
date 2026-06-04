"""
Prompt assembly utility — Phase 5 of the intelligence upgrade.

Provides deterministic, deduplicated, token-budgeted prompt construction.
All LLM-facing prompts should use assemble_prompt() instead of raw string
concatenation so the system enforces consistent structure and token limits.
"""

import logging

_logger = logging.getLogger(__name__)


def assemble_prompt(
    sections: list[tuple[str, str]],
    budget_chars: int | None = None,
) -> str:
    """
    Build a prompt from (label, content) section pairs.

    Guarantees:
    - Empty/whitespace-only sections are skipped.
    - Duplicate sections (same first 200 non-whitespace chars) appear only once —
      the first occurrence is kept and later duplicates are silently dropped.
    - When total length exceeds budget_chars, the string is trimmed from the END
      (lowest-priority content), cutting at the nearest newline. A notice is appended.

    Caller controls priority by section ordering — put high-priority content first
    (task instructions, constraints), low-priority content last (raw research text).

    Returns: clean, double-newline-separated assembled prompt string.
    """
    seen_keys: set[str] = set()
    parts: list[str] = []

    for label, content in sections:
        if not content or not content.strip():
            continue
        content_stripped = content.strip()
        # Dedup key: first 200 non-whitespace chars
        dedup_key = "".join(content_stripped.split())[:200]
        if dedup_key in seen_keys:
            _logger.debug("[prompt_builder] dedup: dropped duplicate section '%s'", label)
            continue
        seen_keys.add(dedup_key)
        parts.append(content_stripped)

    result = "\n\n".join(parts)

    if budget_chars and len(result) > budget_chars:
        _logger.warning(
            "[prompt_builder] trimming prompt %d → %d chars (budget enforced)",
            len(result), budget_chars,
        )
        trimmed = result[:budget_chars]
        # Try to cut at a clean newline boundary rather than mid-sentence
        last_nl = trimmed.rfind("\n", int(budget_chars * 0.75))
        if last_nl > 0:
            trimmed = trimmed[:last_nl]
        result = trimmed + "\n\n[...context trimmed to fit token budget]"

    return result


def estimate_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per English token (conservative)."""
    return max(1, len(text) // 4)


# Provider-aware character budgets (tokens * ~4 chars/token).
# Conservative: assumes worst-case token/char ratio and reserves output capacity.
_PROVIDER_BUDGETS: dict[str, int] = {
    "groq":      120_000,    # llama-3.3-70b: 32K token context − 2K output = 30K * 4
    "cerebras":   24_000,    # llama-3.1-8b:  8K token context − 2K output =  6K * 4
    "gemini":    800_000,    # 1M context, practical cap at ~200K tokens
    "mistral":    96_000,    # 32K context − 8K output = 24K * 4
    "openrouter": 80_000,    # conservative mixed-model default
}


def provider_char_budget(provider: str) -> int:
    """Return the maximum safe prompt character budget for a given provider."""
    return _PROVIDER_BUDGETS.get(provider, 24_000)
