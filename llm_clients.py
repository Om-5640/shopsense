"""
Multi-LLM clients.

Architecture:
- Gemini 2.5 Flash: source analysis (needs 1M context), category, criteria, rubric
- Groq + Llama 3.3 70B: per-product scoring (fast, generous free tier, no rate limits)
- Mistral Small/Medium: interview question generation (natural conversational tone)

Each client has retries, timeout handling, and graceful fallback.

Free tier signup links:
- Gemini: https://aistudio.google.com/apikey
- Groq: https://console.groq.com
- Mistral: https://console.mistral.ai
"""

import os
import json
import time
import re
import random
import collections
import threading
import requests
from typing import Any
from dotenv import load_dotenv

load_dotenv()

# Source analysis constants
MAX_INPUT_CHARS = 200_000
MAX_OUTPUT_TOKENS = 65_000

# ---- API keys ----
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# ---- Endpoints (centralized in models.py - change there to swap models) ----
from models import (
    GEMINI_MODEL, GROQ_MODEL, MISTRAL_MODEL, CEREBRAS_MODEL, OPENROUTER_MODEL,
    GROQ_URL, MISTRAL_URL, CEREBRAS_URL, OPENROUTER_URL,
    GEMINI_TIMEOUT, GROQ_TIMEOUT, MISTRAL_TIMEOUT, CEREBRAS_TIMEOUT, OPENROUTER_TIMEOUT,
    gemini_url,
)

GEMINI_URL = gemini_url()  # computed from current GEMINI_MODEL


# ---- Circuit Breaker (per-provider temporary cooldowns) ----

class _CircuitBreaker:
    """Per-provider circuit breaker with rolling failure window.

    Two failure modes:
    - Explicit block: 429 repeats → 60s cooldown; 502/503 → 120s cooldown
    - Auto-trip: >50% failure rate over last 10 calls → 120s cooldown
    """
    _WINDOW = 10
    _TRIP_THRESHOLD = 0.50
    _COOLDOWN_SHORT = 60
    _COOLDOWN_LONG = 120

    def __init__(self):
        self._lock = threading.Lock()
        self._outcomes: dict[str, collections.deque] = {}
        self._blocked: dict[str, tuple[float, str]] = {}  # provider → (until_ts, reason)

    def record_success(self, provider: str):
        with self._lock:
            self._outcomes.setdefault(provider, collections.deque(maxlen=self._WINDOW)).append(True)

    def record_failure(self, provider: str, status_code: int | None = None):
        with self._lock:
            dq = self._outcomes.setdefault(provider, collections.deque(maxlen=self._WINDOW))
            dq.append(False)
            recent = list(dq)
            if len(recent) >= 5 and recent.count(False) / len(recent) > self._TRIP_THRESHOLD:
                until = time.time() + self._COOLDOWN_LONG
                self._blocked[provider] = (until, f"circuit open: {recent.count(False)/len(recent):.0%} failure")
                return
            if status_code in (502, 503):
                self._blocked[provider] = (time.time() + self._COOLDOWN_LONG, f"HTTP {status_code}")

    def is_blocked(self, provider: str) -> bool:
        with self._lock:
            if provider not in self._blocked:
                return False
            until, _ = self._blocked[provider]
            if time.time() >= until:
                del self._blocked[provider]
                return False
            return True

    def block_temporarily(self, provider: str, seconds: int, reason: str):
        with self._lock:
            self._blocked[provider] = (time.time() + seconds, reason)

    def get_status(self) -> dict:
        now = time.time()
        with self._lock:
            all_providers = set(self._outcomes) | set(self._blocked)
            result = {}
            for p in all_providers:
                outcomes = list(self._outcomes.get(p, []))
                until, reason = self._blocked.get(p, (0, ""))
                blocked = until > now
                result[p] = {
                    "blocked": blocked,
                    "blocked_until": round(until - now) if blocked else 0,
                    "reason": reason if blocked else "",
                    "success_rate": round(outcomes.count(True) / len(outcomes), 2) if outcomes else None,
                    "recent_calls": len(outcomes),
                }
            return result


_cb = _CircuitBreaker()


def is_circuit_broken(provider: str) -> bool:
    """Returns True if provider is temporarily blocked by circuit breaker."""
    return _cb.is_blocked(provider)


def get_circuit_breaker_status() -> dict:
    """Return per-provider circuit breaker state for diagnostics."""
    return _cb.get_status()


# ---- Smart POST helper with error-type-aware retry ----

def _smart_post_with_retry(url, headers, body, provider: str, timeout: int = 180, max_attempts: int = 3):
    """
    Error-type-aware retry with exponential backoff and circuit breaker.

    - 429 → respect Retry-After or 2s/5s backoff; block 60s after exhausted retries
    - 502/503 → block 120s immediately, raise
    - 401/403 → raise ProviderAuthError immediately (caller marks dead permanently)
    - Timeout → raise immediately, no sleep (try a different provider)
    - Other → 2s → 5s backoff
    """
    if _cb.is_blocked(provider):
        raise RuntimeError(f"[circuit:{provider}] temporarily blocked, skipping")

    _BACKOFFS = [2, 5]
    last_err = None

    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            status = resp.status_code

            if status == 429:
                retry_after = None
                try:
                    retry_after = float(resp.headers.get("retry-after", ""))
                except (ValueError, TypeError):
                    pass
                wait = retry_after if retry_after else (_BACKOFFS[min(attempt, 1)] + random.uniform(0, 1))
                last_err = requests.HTTPError(f"429 Too Many Requests", response=resp)
                if attempt < max_attempts - 1 and wait <= 30:
                    print(f"  [{provider}] 429 rate limit, backing off {wait:.1f}s...")
                    time.sleep(wait)
                    continue
                _cb.block_temporarily(provider, _cb._COOLDOWN_SHORT, "429 repeated")
                _cb.record_failure(provider, 429)
                raise last_err

            elif status in (502, 503):
                _cb.block_temporarily(provider, _cb._COOLDOWN_LONG, f"HTTP {status}")
                _cb.record_failure(provider, status)
                raise requests.HTTPError(f"HTTP {status} - provider down", response=resp)

            elif status in (401, 403):
                _cb.record_failure(provider, status)
                raise ProviderAuthError(f"{provider} auth failed (HTTP {status}). Check API key.")

            resp.raise_for_status()
            _cb.record_success(provider)
            return resp

        except (ProviderAuthError, requests.exceptions.Timeout):
            raise  # fail fast, no retry

        except requests.HTTPError as e:
            last_err = e
            if attempt < max_attempts - 1:
                wait = _BACKOFFS[min(attempt, 1)] + random.uniform(0, 1)
                print(f"  [{provider}] HTTP error attempt {attempt + 1}, retrying in {wait:.1f}s...")
                time.sleep(wait)

        except Exception as e:
            last_err = e
            _cb.record_failure(provider)
            if attempt < max_attempts - 1:
                wait = _BACKOFFS[min(attempt, 1)] + random.uniform(0, 1)
                print(f"  [{provider}] attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait:.1f}s...")
                time.sleep(wait)

    raise last_err


# ---- GEMINI ----

def call_gemini(prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 65_000) -> tuple[str, str]:
    """Returns (text, finish_reason). Used for: category, criteria, rubric, analysis."""
    if not GEMINI_API_KEY:
        raise RuntimeError("Set GEMINI_API_KEY env var. Get one at https://aistudio.google.com/apikey")

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    resp = _smart_post_with_retry(url, {"Content-Type": "application/json"}, body, "gemini", timeout=GEMINI_TIMEOUT)
    data = resp.json()

    try:
        cand = data["candidates"][0]
        finish = cand.get("finishReason", "STOP")
        text = cand["content"]["parts"][0]["text"]
        return text, finish
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response: {json.dumps(data)[:500]}") from e


# ---- QUALITY-FIRST FALLBACK ----
# Try Gemini first (better quality), fall back to Groq if quota hit or any error.

def call_gemini_with_groq_fallback(
    prompt: str,
    system: str = "",
    json_mode: bool = False,
    max_tokens: int = 8192,
) -> str:
    """
    Returns text. Tries Gemini first for quality, falls back to Groq on:
    - 429 rate/quota errors
    - timeouts / connection errors
    - any unexpected error
    Groq Llama 3.3 70B is the fallback - still very capable for structured tasks.
    """
    if GEMINI_API_KEY:
        try:
            text, _ = call_gemini(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
            return text
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "rate" in err_str:
                print(f"[fallback] Gemini quota/rate hit. Switching to Groq.")
            else:
                print(f"[fallback] Gemini failed ({type(e).__name__}). Switching to Groq.")

    # Fall through to Groq
    if not GROQ_API_KEY:
        raise RuntimeError("Both Gemini failed and Groq not configured. Set GROQ_API_KEY.")
    return call_groq(prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)


# ---- GROQ (used for scoring) ----

def call_groq(prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 4096) -> str:
    """
    Returns text. Used for: per-product scoring.
    Groq's free tier: ~14,400 req/day, very fast, generous rate limits.
    """
    if not GROQ_API_KEY:
        # Fallback to Gemini if Groq not configured
        print("[groq] not configured, falling back to Gemini")
        text, _ = call_gemini(prompt, system=system, json_mode=json_mode)
        return text

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # Smart retry: Groq returns a Retry-After header on 429. Respect it instead of fixed backoff.
    resp = _groq_post_with_smart_retry(GROQ_URL, headers, body, max_attempts=4)
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Groq response: {json.dumps(data)[:500]}") from e


class GroqQuotaExhausted(Exception):
    """Raised when Groq returns a retry-after longer than QUOTA_EXHAUSTION_THRESHOLD.
    Indicates daily quota is gone, not transient rate limit. Caller should bail."""
    pass


class ProviderAuthError(Exception):
    """Raised when a provider returns 401/403. Caller should permanently mark this provider dead."""
    pass


def _groq_post_with_smart_retry(url, headers, body, max_attempts=3):
    """Groq-aware retry with quota-exhaustion detection and circuit breaker.

    Two-tier 429 handling:
    - retry_after <= 120s → transient rate limit, sleep & retry
    - retry_after > 120s  → daily token quota exhausted, raise GroqQuotaExhausted

    Also handles: 401/403 → ProviderAuthError; 502/503 → block 120s.
    Records outcomes in global circuit breaker for cross-provider awareness.
    """
    MAX_RETRY_WAIT_SECONDS = 60
    QUOTA_EXHAUSTION_THRESHOLD = 120

    if _cb.is_blocked("groq"):
        raise RuntimeError("[circuit:groq] temporarily blocked, skipping")

    last_err = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=GROQ_TIMEOUT)
            status = resp.status_code

            if status in (401, 403):
                _cb.record_failure("groq", status)
                raise ProviderAuthError(f"Groq auth failed (HTTP {status}). Check GROQ_API_KEY.")

            if status in (502, 503):
                _cb.block_temporarily("groq", _cb._COOLDOWN_LONG, f"HTTP {status}")
                _cb.record_failure("groq", status)
                raise requests.HTTPError(f"HTTP {status} - Groq down", response=resp)

            if status == 429:
                retry_after = resp.headers.get("retry-after", "")
                requested_wait = None
                try:
                    requested_wait = float(retry_after)
                except ValueError:
                    pass

                if requested_wait and requested_wait > QUOTA_EXHAUSTION_THRESHOLD:
                    _cb.record_failure("groq", 429)
                    raise GroqQuotaExhausted(
                        f"Groq daily quota exhausted (asked us to wait {requested_wait:.0f}s = "
                        f"{requested_wait/60:.1f} min). Stopping further calls."
                    )

                wait = requested_wait if requested_wait else (5 * (2 ** attempt) + random.uniform(0, 2))
                wait = min(wait, MAX_RETRY_WAIT_SECONDS)
                _cb.record_failure("groq", 429)
                if attempt < max_attempts - 1:
                    print(f"  [groq 429] rate limit, sleeping {wait:.1f}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            _cb.record_success("groq")
            return resp

        except (GroqQuotaExhausted, ProviderAuthError):
            raise  # bubble up, don't retry
        except Exception as e:
            last_err = e
            _cb.record_failure("groq")
            if attempt < max_attempts - 1:
                wait = 10 + random.uniform(0, 3)
                print(f"  [groq] attempt {attempt + 1} failed ({type(e).__name__}). Retrying in {wait:.1f}s...")
                time.sleep(wait)
    raise last_err


# ---- MISTRAL (used for interview) ----

def call_mistral(prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 2048) -> str:
    """
    Returns text. Used for: interview question generation.
    Mistral has a more natural conversational style than Gemini.
    """
    if not MISTRAL_API_KEY:
        # Fallback to Gemini if Mistral not configured
        print("[mistral] not configured, falling back to Gemini")
        text, _ = call_gemini(prompt, system=system, json_mode=json_mode)
        return text

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "model": MISTRAL_MODEL,
        "messages": messages,
        "temperature": 0.7,  # higher temp = more natural conversation
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = _smart_post_with_retry(MISTRAL_URL, headers, body, "mistral", timeout=MISTRAL_TIMEOUT)
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Mistral response: {json.dumps(data)[:500]}") from e


# ---- CEREBRAS (alternative fast Llama provider, separate quota from Groq) ----

def call_cerebras(prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 2048) -> str:
    """
    Returns text. Cerebras has free Llama 3.3 70B with a separate quota from Groq.
    Used in the parallel provider pool to multiply effective rate limit.
    """
    if not CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY not set. Get free key at https://cloud.cerebras.ai")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "model": CEREBRAS_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {CEREBRAS_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = _smart_post_with_retry(CEREBRAS_URL, headers, body, "cerebras", timeout=CEREBRAS_TIMEOUT)
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Cerebras response: {json.dumps(data)[:500]}") from e


def has_cerebras() -> bool:
    return bool(CEREBRAS_API_KEY)


# ---- OPENROUTER (master fallback - gateway to many free models) ----

def call_openrouter(prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 2048) -> str:
    """
    Returns text. OpenRouter is the master fallback - it has multiple free models
    behind one endpoint, so even if a specific model is rate-limited, others work.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set. Get free key at https://openrouter.ai/keys")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body: dict[str, Any] = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # OpenRouter recommended headers for tracking
        "HTTP-Referer": "https://github.com/local/shopping-agent",
        "X-Title": "Shopping Research Agent",
    }

    resp = _smart_post_with_retry(OPENROUTER_URL, headers, body, "openrouter", timeout=OPENROUTER_TIMEOUT)
    data = resp.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:500]}") from e


def has_openrouter() -> bool:
    return bool(OPENROUTER_API_KEY)