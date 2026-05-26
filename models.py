"""
Central model configuration.

ONE FILE to change any model used anywhere in the system.
To swap (e.g.) Gemini for Claude, just change GEMINI_MODEL here.

Each provider has:
  PROVIDER_MODEL → the specific model ID
  PROVIDER_URL   → the API endpoint
  PROVIDER_TIMEOUT → per-request timeout in seconds

PROVIDER POOL for HIGH-VOLUME TASKS (thread summarization):
We round-robin across 4 free providers to multiply our effective rate limit.
Each provider's free tier has independent quota — using all 4 = 4x capacity.
"""

# ---- Gemini (Google AI Studio, free tier - 250 req/day, 10 RPM) ----
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT = 120

# ---- Groq (free, fast - 14,400 req/day, 30 RPM) ----
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT = 60

# ---- Mistral (free tier - 1B tokens/month, 1 RPS) ----
MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_TIMEOUT = 60

# ---- Cerebras (free - 14,400 req/day, separate from Groq's quota) ----
# Get free key: https://cloud.cerebras.ai
CEREBRAS_MODEL = "llama-3.3-70b"
CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_TIMEOUT = 60

# ---- OpenRouter (MASTER FALLBACK) ----
# Gateway to many free models. When all other providers fail, this is the safety net.
# Get free key: https://openrouter.ai/keys
# Default uses the free Llama 3.3 70B. Can be swapped to any OpenRouter model.
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT = 90

# Provider pool for high-volume parallel tasks (thread summarization).
# Order them by speed: fastest first.
PARALLEL_PROVIDER_POOL = ["groq", "cerebras", "gemini", "mistral"]

# Master fallback - tried last in every agent's fallback chain when all else fails.
MASTER_FALLBACK = "openrouter"


def gemini_url() -> str:
    """Build full Gemini URL with current model substituted in."""
    return GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL)