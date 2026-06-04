"""
Online evaluation — measures REAL pipeline output on live queries.

Unlike the offline benchmark (synthetic, deterministic scoring math), the online eval runs
the actual research pipeline end-to-end and scores genuine LLM output for retrieval coverage
and explanation grounding. Because it consumes free-tier API quota, it is intentionally:

  - capped at 2 queries (free-tier rate limits)
  - NOT run on every PR — it is a manual / nightly job
  - the source of recorded fixtures that keep the offline online-metrics honest

Commands:
    python -m evals.online.record    # run 2 real queries, capture fixtures, print real scores
"""

# Hard cap — free-tier providers rate-limit aggressively beyond this.
MAX_ONLINE_QUERIES = 2

# The fixed query set the online eval and recorder use.
ONLINE_QUERIES: list[dict] = [
    {"query": "best wireless earbuds under 3000 for gym", "category": "electronics/earbuds", "region": "india"},
    {"query": "best budget mechanical keyboard for programming", "category": "electronics/keyboard-mechanical", "region": "usa"},
]
