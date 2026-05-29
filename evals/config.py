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
    "explanation_integrity":      0.05,
    "robustness":                 0.05,
    "human_alignment":            0.05,
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
}

# ── CI blocking thresholds (fail build below these) ───────────────────────
CI_BLOCK_THRESHOLDS: dict[str, float] = {
    "recommendation_quality":     60.0,
    "counterfactual_sensitivity": 55.0,
    "robustness":                 70.0,
}

# Minimum Intelligence Index to pass CI
CI_MIN_INDEX: float = 65.0

# ── Eval modes ────────────────────────────────────────────────────────────
QUICK_EVAL_METRICS = [
    "recommendation_quality",
    "personalization_strength",
    "counterfactual_sensitivity",
    "ranking_quality",
    "robustness",
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
