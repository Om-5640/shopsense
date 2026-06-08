"""
Global configuration for the ShopSense eval platform.
"""

from __future__ import annotations

# ── Intelligence Index weights (must sum to 1.0) ──────────────────────────
INDEX_WEIGHTS: dict[str, float] = {
    "recommendation_quality":     0.20,
    "personalization_strength":   0.15,
    "counterfactual_sensitivity": 0.15,
    "ranking_quality":            0.15,
    "semantic_consistency":       0.10,
    "retrieval_quality":          0.10,
    "explanation_integrity":      0.02,
    "robustness":                 0.05,
    "human_alignment":            0.05,
    "stage_isolation":            0.03,
}

# ── Pass thresholds per metric (0-100) ────────────────────────────────────
PASS_THRESHOLDS: dict[str, float] = {
    "recommendation_quality":     72.0,
    "personalization_strength":   65.0,
    "counterfactual_sensitivity": 70.0,
    "ranking_quality":            70.0,
    "semantic_consistency":       68.0,
    "retrieval_quality":          60.0,
    "explanation_integrity":      65.0,
    "robustness":                 80.0,
    "human_alignment":            60.0,
    "stage_isolation":            90.0,
}

# ── CI blocking thresholds (fail build below these) ───────────────────────
# These gate the deterministic offline metrics, which are fully stable run-to-run
# (no LLM calls). Each sits ~10pt below its current cross-category score, so a real
# regression fails the build immediately while legitimate small changes have headroom.
# Online-only metrics (retrieval/explanation) are not gated here — they skip offline.
CI_BLOCK_THRESHOLDS: dict[str, float] = {
    "recommendation_quality":     90.0,   # current 100.0
    "personalization_strength":   80.0,   # current  92.5
    "counterfactual_sensitivity": 88.0,   # current 100.0
    "ranking_quality":            90.0,   # current 100.0
    "semantic_consistency":       85.0,   # current  96.0
    "robustness":                 90.0,   # current 100.0
    "human_alignment":            65.0,   # current  76.9 (cross-category expert panel)
    "stage_isolation":            80.0,   # deterministic — any drop means inject_fault regression
}

# Minimum Intelligence Index to pass CI (current full-mode index ≈ 96.8).
CI_MIN_INDEX: float = 88.0

# ── Eval modes ────────────────────────────────────────────────────────────
QUICK_EVAL_METRICS = [
    "recommendation_quality",
    "personalization_strength",
    "counterfactual_sensitivity",
    "ranking_quality",
    "robustness",
    "stage_isolation",
]

FULL_EVAL_METRICS = list(INDEX_WEIGHTS.keys())

# Metrics that require a live/saved pipeline run (not pure offline math)
ONLINE_METRICS = [
    "semantic_consistency",
    "retrieval_quality",
    "explanation_integrity",
    "human_alignment",
]

# ── History ───────────────────────────────────────────────────────────────
HISTORY_FILE = "evals/data/history/runs.jsonl"
MAX_HISTORY_RUNS = 500

# ── Report settings ───────────────────────────────────────────────────────
REPORT_DIR = "evals/data/reports"
HTML_REPORT_TITLE = "ShopSense Intelligence Eval"
