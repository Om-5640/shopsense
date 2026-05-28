"""
Agent registry with round-robin provider pool and per-task fallback chains.

KEY DESIGN:
- High-volume parallel tasks (thread_summarizer) use a POOL of providers
  in round-robin fashion (4 providers = 4x effective rate limit)
- Every agent has a fallback_chain walked top-to-bottom on failure
- OpenRouter is the MASTER FALLBACK - tried last when all others die
- "Once-failed" tracking: if a provider has fully failed during this run
  (e.g., GroqQuotaExhausted), we skip it on subsequent calls to save time

To tune behavior, edit ONE agent block here.

USAGE:
    from agents import run_agent
    result = run_agent("category_detector", user_prompt="...")
"""

import itertools
import logging
import os
import threading

_logger = logging.getLogger(__name__)

from llm_clients import (
    call_groq, call_gemini, call_mistral, call_cerebras, call_openrouter,
    GroqQuotaExhausted, ProviderAuthError,
    has_cerebras, has_openrouter,
    is_circuit_broken, get_circuit_breaker_status,
)


# Master fallback added to every chain
_MASTER = "openrouter"


AGENTS = {
    "category_detector": {
        "provider": "groq",
        "fallback_chain": ["cerebras", "gemini", "mistral", _MASTER],
        "temperature": 0.1,
        "max_tokens": 1024,
        "json_mode": True,
        "description": "Classify shopping queries with disambiguation",
    },
    "criteria_generator": {
        "provider": "gemini",
        "fallback_chain": ["groq", "cerebras", "mistral", _MASTER],
        "temperature": 0.3,
        "max_tokens": 2048,
        "json_mode": True,
        "description": "Generate buying criteria for a product category",
    },
    "interview_questioner": {
        "provider": "mistral",
        "fallback_chain": ["gemini", "groq", "cerebras", _MASTER],
        "temperature": 0.7,
        "max_tokens": 1024,
        "json_mode": True,
        "description": "Generate next interview question, coverage-aware",
    },
    "preference_summarizer": {
        "provider": "mistral",
        "fallback_chain": ["gemini", "groq", "cerebras", _MASTER],
        "temperature": 0.3,
        "max_tokens": 1024,
        "json_mode": True,
        "description": "Summarize interview Q&A into structured intent + text summary",
    },
    "rubric_generator": {
        "provider": "gemini",
        "fallback_chain": ["groq", "cerebras", "mistral", _MASTER],
        "temperature": 0.2,
        "max_tokens": 3072,
        "json_mode": True,
        "description": "Build weighted scorecard from profile + criteria",
    },
    "gap_filler": {
        "provider": "gemini",
        "fallback_chain": ["groq", "cerebras", "mistral", _MASTER],
        "temperature": 0.2,
        "max_tokens": 2048,
        "json_mode": True,
        "description": "Infer weights for uncovered criteria from research signal",
    },
    "thread_summarizer": {
        "provider": "pool",
        "provider_pool": ["groq", "cerebras", "gemini", "mistral"],
        "fallback_chain": ["groq", "cerebras", "gemini", "mistral", _MASTER],
        "temperature": 0.2,
        "max_tokens": 2048,
        "json_mode": True,
        "description": "Summarize ONE Reddit thread into structured form (parallel)",
    },
    "main_analyzer": {
        "provider": "gemini",
        "fallback_chain": ["groq", "cerebras", "mistral", _MASTER],
        "temperature": 0.2,
        "max_tokens": 8192,
        "json_mode": True,
        "description": "Aggregate thread summaries + reviews into ranked products",
    },
    "product_scorer": {
        "provider": "groq",
        "fallback_chain": ["cerebras", "gemini", "mistral", _MASTER],
        "temperature": 0.1,
        "max_tokens": 2048,
        "json_mode": True,
        "description": "Score one product against the rubric with evidence",
    },
    "explanation_writer": {
        "provider": "groq",
        "fallback_chain": ["cerebras", "mistral", "gemini", _MASTER],
        "temperature": 0.5,
        "max_tokens": 512,
        "json_mode": False,
        "description": "Write 'why this product fits you' explanations",
    },
    # ---- v7 agents ----
    "cross_validator": {
        "provider": "gemini",
        "fallback_chain": ["groq", "cerebras", "mistral", _MASTER],
        "temperature": 0.1,
        "max_tokens": 1024,
        "json_mode": True,
        "description": "Compare product sentiment across subreddits to detect community bias",
    },
    "signal_extractor": {
        "provider": "groq",
        "fallback_chain": ["cerebras", "gemini", "mistral", _MASTER],
        "temperature": 0.1,
        "max_tokens": 1024,
        "json_mode": True,
        "description": "Extract durable user preference signals from interview Q&A",
    },
    # ---- v9 agents ----
    "sentiment_analyser": {
        "provider": "groq",
        "fallback_chain": ["cerebras", "gemini", "mistral", _MASTER],
        "temperature": 0.1,
        "max_tokens": 512,
        "json_mode": True,
        "description": "Score sentiment per product per comment (called only when product confirmed present)",
    },
}


# Thread-safe round-robin counters per pool agent.
_pool_lock = threading.Lock()
_pool_counters: dict = {}

# Session-level "fully dead" provider tracker - skip these in future calls
# (e.g., once GroqQuotaExhausted fires, no point hammering Groq for the rest of this run)
_dead_providers: set = set()
_dead_lock = threading.Lock()


def mark_provider_dead(provider: str) -> None:
    """Mark a provider as dead for the rest of this run. Subsequent calls skip it."""
    with _dead_lock:
        if provider not in _dead_providers:
            _dead_providers.add(provider)
            _logger.warning("[provider:%s] marked dead for this session (will be skipped)", provider)


def is_provider_dead(provider: str) -> bool:
    return provider in _dead_providers


def reset_dead_providers() -> None:
    """Clear the dead set. Useful for tests or long-running sessions across days."""
    with _dead_lock:
        _dead_providers.clear()


def _available_for_pool(pool: list) -> list:
    """Filter pool to providers that are configured, not session-dead, and not circuit-broken."""
    return [p for p in pool if _is_provider_available(p) and not is_provider_dead(p) and not is_circuit_broken(p)]


def _next_from_pool(agent_name: str, pool: list) -> str:
    """Get the next provider from a round-robin cycle, thread-safe.
    Excludes dead providers and unconfigured providers automatically."""
    available_pool = _available_for_pool(pool)
    if not available_pool:
        # All dead - fall through to master if available
        if _is_provider_available(_MASTER) and not is_provider_dead(_MASTER):
            return _MASTER
        raise RuntimeError(f"No providers available in pool for {agent_name}: {pool}")
    with _pool_lock:
        key = f"{agent_name}|{','.join(available_pool)}"
        if key not in _pool_counters:
            _pool_counters[key] = itertools.cycle(available_pool)
        return next(_pool_counters[key])


def run_agent(agent_name: str, user_prompt: str, system: str = "") -> str:
    """
    Run a named agent with full fallback resilience.

    Behavior:
    - If provider="pool", round-robin pick a provider from provider_pool
    - On failure, walk the fallback_chain in order
    - Skips dead providers (fully exhausted earlier in this session)
    - OpenRouter master fallback is tried LAST
    - Returns the FIRST successful response
    - Only raises if EVERY available provider fails
    """
    if agent_name not in AGENTS:
        raise ValueError(f"Unknown agent: {agent_name}. Available: {list(AGENTS.keys())}")

    cfg = AGENTS[agent_name]
    json_mode = cfg.get("json_mode", False)
    max_tokens = cfg.get("max_tokens", 2048)

    # Pick primary provider
    if cfg["provider"] == "pool":
        primary = _next_from_pool(agent_name, cfg["provider_pool"])
    else:
        primary = cfg["provider"]

    # Build attempt order: primary first, then fallbacks (dedup)
    attempt_order = [primary]
    for fb in cfg.get("fallback_chain", []):
        if fb not in attempt_order:
            attempt_order.append(fb)

    # Skip providers that aren't configured, session-dead, or circuit-broken
    available = [
        p for p in attempt_order
        if _is_provider_available(p) and not is_provider_dead(p) and not is_circuit_broken(p)
    ]
    if not available:
        # Last resort: try master even if marked dead (maybe transient)
        if _is_provider_available(_MASTER):
            available = [_MASTER]
        else:
            raise RuntimeError(
                f"No providers configured for {agent_name}. Set env vars: GROQ_API_KEY, "
                f"GEMINI_API_KEY, MISTRAL_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY"
            )

    last_err = None
    for i, provider in enumerate(available):
        try:
            return _dispatch(provider, user_prompt, system, json_mode, max_tokens)
        except GroqQuotaExhausted as e:
            mark_provider_dead("groq")
            last_err = e
            if i < len(available) - 1:
                _logger.warning("[%s] groq quota exhausted, trying %s", agent_name, available[i + 1])
        except ProviderAuthError as e:
            # Auth failure = permanently bad key; mark dead for entire session
            mark_provider_dead(provider)
            last_err = e
            if i < len(available) - 1:
                _logger.warning("[%s] %s auth failed, trying %s", agent_name, provider, available[i + 1])
            else:
                _logger.warning("[%s] %s auth failed (no more providers)", agent_name, provider)
        except Exception as e:
            last_err = e
            err_type = type(e).__name__
            err_str = str(e).lower()
            if "quota" in err_str or "exhausted" in err_str:
                mark_provider_dead(provider)
            if i < len(available) - 1:
                _logger.warning("[%s] %s failed (%s), trying %s", agent_name, provider, err_type, available[i + 1])
            else:
                _logger.warning("[%s] all providers failed (last: %s/%s)", agent_name, provider, err_type)
    raise last_err


def _is_provider_available(provider: str) -> bool:
    """Check if a provider has an API key configured."""
    if provider == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    elif provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    elif provider == "mistral":
        return bool(os.environ.get("MISTRAL_API_KEY"))
    elif provider == "cerebras":
        return has_cerebras()
    elif provider == "openrouter":
        return has_openrouter()
    return False


def _dispatch(provider: str, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    """Route to the right LLM client based on provider name."""
    if provider == "groq":
        return call_groq(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
    elif provider == "gemini":
        text, _ = call_gemini(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
        return text
    elif provider == "mistral":
        return call_mistral(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
    elif provider == "cerebras":
        return call_cerebras(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
    elif provider == "openrouter":
        return call_openrouter(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def get_agent_config(agent_name: str) -> dict:
    return dict(AGENTS.get(agent_name, {}))


def get_provider_status() -> dict:
    """Return per-provider status: configured, session-alive, circuit-breaker state."""
    cb_status = get_circuit_breaker_status()
    return {
        provider: {
            "configured": _is_provider_available(provider),
            "session_alive": not is_provider_dead(provider),
            "circuit_blocked": is_circuit_broken(provider),
            "circuit_detail": cb_status.get(provider, {}),
        }
        for provider in ["groq", "gemini", "mistral", "cerebras", "openrouter"]
    }