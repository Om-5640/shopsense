"""
ShopSense Intelligence Evaluation Platform

Run with:
    python -m evals              # quick offline eval
    python -m evals full         # full suite
    python -m evals tournament   # candidate vs production
    python -m evals ci           # CI gate (exits non-zero on regression)
    python -m evals history      # show past runs
"""

from .runner import EvalRunner
from .index import compute_index
from .history import EvalHistory

__version__ = "1.0.0"
__all__ = ["EvalRunner", "compute_index", "EvalHistory"]
