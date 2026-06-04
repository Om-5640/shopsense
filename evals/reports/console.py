"""
Console report for eval runs. Designed for terminal readability.
Uses ASCII-only symbols for Windows cp1252 compatibility.
"""

from __future__ import annotations
from evals.runner import EvalRunResult
from evals.config import INDEX_WEIGHTS


def print_report(result: EvalRunResult) -> None:
    idx = result.intelligence_index
    grade = result.index_breakdown.get("grade", "?")
    regression = result.regression_report

    # Header
    print(f"\n{'='*64}")
    print(f"  ShopSense Intelligence Report  [{result.mode.upper()}]")
    print(f"  Run {result.run_id}  |  {result.timestamp[:10]}  |  {result.commit}@{result.branch}")
    print(f"{'='*64}")

    # Intelligence Index
    bar_len = int(idx / 5)
    bar = "#" * bar_len + "-" * (20 - bar_len)
    print(f"\n  Intelligence Index:  {idx:.1f} / 100  [{grade}]")
    print(f"  [{bar}]")

    # Regression status
    if regression.get("regressions"):
        print(f"\n  [REGRESSIONS vs commit {regression.get('baseline_commit', '?')}]")
        for r in regression["regressions"]:
            print(f"     {r['metric']:30}  {r['baseline']:.1f} -> {r['current']:.1f}  ({r['delta']:+.1f})")
    elif regression.get("improvements"):
        print(f"\n  [IMPROVED vs baseline]")
        for r in regression["improvements"]:
            print(f"     {r['metric']:30}  {r['baseline']:.1f} -> {r['current']:.1f}  ({r['delta']:+.1f})")

    # Metric breakdown table
    print(f"\n  {'Metric':<35}  {'Score':>6}  {'Wt':>4}  {'Contrib':>7}  {'Grd':>4}  Status")
    print(f"  {'-'*35}  {'-'*6}  {'-'*4}  {'-'*7}  {'-'*4}  {'-'*6}")

    components = result.index_breakdown.get("components", {})
    for metric, data in sorted(components.items(), key=lambda x: -x[1]["weight"]):
        score = data["score"]
        weight = data["weight"]
        contrib = data["contribution"]
        grade_m = data["grade"]
        if data.get("skipped"):
            print(
                f"  {metric:<35}  {'n/a':>6}  {weight:>4.2f}  {'n/a':>7}  {grade_m:>4}  SKIP (online-only)"
            )
            continue
        status = "PASS" if data["passed"] else "FAIL"
        print(
            f"  {metric:<35}  {score:>6.1f}  {weight:>4.2f}  {contrib:>7.2f}  {grade_m:>4}  {status}"
        )

    # Pass rate
    print(f"\n  Scenarios: {result.scenario_count}  |  Pass rate: {result.pass_rate}%  |  {result.elapsed_s}s elapsed")

    # Failures summary
    failures_by_metric = {
        k: v.failures for k, v in result.metric_results.items() if v.failures
    }
    if failures_by_metric:
        print(f"\n  -- Failures (first 5 per metric) --")
        for metric, failures in failures_by_metric.items():
            print(f"\n  [{metric}]")
            for f in failures[:5]:
                print(f"    ! {f}")

    print(f"\n{'='*64}\n")
