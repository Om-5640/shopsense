"""
JSON report writer. Saves full eval run result to disk.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from evals.runner import EvalRunResult
from evals.config import REPORT_DIR


def write_json_report(result: EvalRunResult, path: str | None = None) -> str:
    out_dir = Path(path or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = out_dir / f"eval_{result.run_id}.json"

    payload = {
        "run_id": result.run_id,
        "mode": result.mode,
        "timestamp": result.timestamp,
        "commit": result.commit,
        "branch": result.branch,
        "elapsed_s": result.elapsed_s,
        "intelligence_index": result.intelligence_index,
        "index_breakdown": result.index_breakdown,
        "scenario_count": result.scenario_count,
        "pass_rate": result.pass_rate,
        "regression_report": result.regression_report,
        "metrics": {
            k: {
                "score": v.score,
                "passed": v.passed,
                "pass_threshold": v.pass_threshold,
                "grade": v.grade,
                "failures": v.failures,
                "details": v.details,
            }
            for k, v in result.metric_results.items()
        },
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"  JSON report: {filename}")
    return str(filename)
