"""
Phase 10: Longitudinal Regression System

Every eval run is appended to a JSONL file so we can:
  - Track score trends over time
  - Detect when a commit caused a regression
  - Compare current run to previous N runs
"""

from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from evals.config import HISTORY_FILE, MAX_HISTORY_RUNS


@dataclass
class HistoryRun:
    run_id: str
    timestamp: str
    commit: str
    branch: str
    mode: str
    intelligence_index: float
    metric_scores: dict[str, float]
    scenario_count: int
    pass_rate: float
    elapsed_s: float
    tags: list[str] = field(default_factory=list)
    notes: str = ""


class EvalHistory:
    def __init__(self, path: str = HISTORY_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, run: HistoryRun) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(run)) + "\n")
        self._trim()

    def load(self, last_n: int | None = None) -> list[HistoryRun]:
        if not self.path.exists():
            return []
        runs = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    runs.append(HistoryRun(**json.loads(line)))
                except Exception:
                    continue
        return runs[-last_n:] if last_n else runs

    def last(self) -> HistoryRun | None:
        runs = self.load(last_n=1)
        return runs[0] if runs else None

    def regression_report(self, current: HistoryRun, window: int = 10) -> dict:
        """Compare current run to the last `window` runs."""
        history = self.load(last_n=window + 1)
        history = [r for r in history if r.run_id != current.run_id]
        if not history:
            return {"status": "no_baseline", "regressions": [], "improvements": []}

        baseline = history[-1]
        regressions = []
        improvements = []

        for metric, current_score in current.metric_scores.items():
            baseline_score = baseline.metric_scores.get(metric)
            if baseline_score is None:
                continue
            delta = current_score - baseline_score
            entry = {
                "metric": metric,
                "current": current_score,
                "baseline": baseline_score,
                "delta": round(delta, 1),
                "baseline_run": baseline.run_id,
                "baseline_commit": baseline.commit,
            }
            if delta < -5.0:
                regressions.append(entry)
            elif delta > 5.0:
                improvements.append(entry)

        index_delta = current.intelligence_index - baseline.intelligence_index

        return {
            "status": "regressed" if regressions else "ok",
            "index_delta": round(index_delta, 1),
            "regressions": sorted(regressions, key=lambda x: x["delta"]),
            "improvements": sorted(improvements, key=lambda x: -x["delta"]),
            "baseline_commit": baseline.commit,
            "baseline_index": baseline.intelligence_index,
        }

    def trend_data(self, last_n: int = 20) -> dict:
        """Return data suitable for chart rendering."""
        runs = self.load(last_n=last_n)
        return {
            "timestamps": [r.timestamp[:10] for r in runs],
            "indices": [r.intelligence_index for r in runs],
            "commits": [r.commit[:7] for r in runs],
            "metric_series": {
                metric: [r.metric_scores.get(metric, 0) for r in runs]
                for metric in {k for r in runs for k in r.metric_scores}
            },
        }

    def _trim(self) -> None:
        runs = self.load()
        if len(runs) > MAX_HISTORY_RUNS:
            with open(self.path, "w", encoding="utf-8") as f:
                for run in runs[-MAX_HISTORY_RUNS:]:
                    f.write(json.dumps(asdict(run)) + "\n")


def get_git_info() -> tuple[str, str]:
    """Return (commit_sha, branch_name). Falls back to 'unknown' if not in a git repo."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return commit, branch
    except Exception:
        return "unknown", "unknown"


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
