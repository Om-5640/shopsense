"""
CLI entry point for the ShopSense eval platform.

Usage:
    python -m evals                          # quick eval (offline)
    python -m evals quick                    # same
    python -m evals full                     # full benchmark suite
    python -m evals tournament               # tournament vs production baseline
    python -m evals history                  # show last 10 runs
    python -m evals history --last 20        # show last 20 runs
    python -m evals ci                       # CI mode — exits non-zero on regression
"""

from __future__ import annotations
import sys
import argparse
from evals.runner import EvalRunner
from evals.reports import print_report, write_json_report, write_html_report
from evals.history import EvalHistory
from evals.config import CI_MIN_INDEX, CI_BLOCK_THRESHOLDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="ShopSense Intelligence Eval Platform",
    )
    sub = parser.add_subparsers(dest="command")

    # quick
    quick_p = sub.add_parser("quick", help="Quick offline eval (default)")
    quick_p.add_argument("--no-history", action="store_true")
    quick_p.add_argument("--json", action="store_true", help="Write JSON report")
    quick_p.add_argument("--html", action="store_true", help="Write HTML report")

    # full
    full_p = sub.add_parser("full", help="Full benchmark suite")
    full_p.add_argument("--no-history", action="store_true")
    full_p.add_argument("--json", action="store_true")
    full_p.add_argument("--html", action="store_true")

    # tournament
    tour_p = sub.add_parser("tournament", help="Tournament: candidate vs production")
    tour_p.add_argument(
        "--amplify", nargs="+", metavar="CRITERION=FACTOR",
        help='Amplify criterion weight for candidate, e.g. noise_cancellation=1.5',
    )

    # history
    hist_p = sub.add_parser("history", help="Show historical runs")
    hist_p.add_argument("--last", type=int, default=10)

    # ci
    ci_p = sub.add_parser("ci", help="CI gate — exits non-zero on regression")
    ci_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    cmd = args.command or "quick"

    if cmd in ("quick", None):
        return _run_eval("quick", args)
    if cmd == "full":
        return _run_eval("full", args)
    if cmd == "tournament":
        return _run_tournament(args)
    if cmd == "history":
        return _show_history(args)
    if cmd == "ci":
        return _run_ci(args)

    parser.print_help()
    return 1


def _run_eval(mode: str, args) -> int:
    runner = EvalRunner(
        mode=mode,
        save_history=not getattr(args, "no_history", False),
    )
    result = runner.run()
    print_report(result)

    if getattr(args, "json", False):
        write_json_report(result)
    if getattr(args, "html", False):
        write_html_report(result)

    return 0


def _run_tournament(args) -> int:
    from evals.tournament import Tournament

    mults: dict[str, float] = {}
    if getattr(args, "amplify", None):
        for item in args.amplify:
            k, _, v = item.partition("=")
            try:
                mults[k.strip()] = float(v.strip())
            except ValueError:
                print(f"  Invalid amplify value: {item}", file=sys.stderr)
                return 2

    t = Tournament(candidate_weight_multipliers=mults or None)
    t.run()
    return 0


def _show_history(args) -> int:
    history = EvalHistory()
    runs = history.load(last_n=args.last)

    if not runs:
        print("  No eval history found.")
        print(f"  Run 'python -m evals quick' to create the first entry.")
        return 0

    print(f"\n  {'Date':<12}  {'Commit':<8}  {'Branch':<20}  {'Mode':<6}  {'Index':>6}  {'Pass%':>6}  {'Time':>6}")
    print(f"  {'─'*12}  {'─'*8}  {'─'*20}  {'─'*6}  {'─'*6}  {'─'*6}  {'─'*6}")
    for r in reversed(runs):
        date = r.timestamp[:10]
        commit = r.commit[:8]
        branch = r.branch[:20]
        mode = r.mode[:6]
        idx = r.intelligence_index
        rate = r.pass_rate
        elapsed = f"{r.elapsed_s:.1f}s"
        print(f"  {date:<12}  {commit:<8}  {branch:<20}  {mode:<6}  {idx:>6.1f}  {rate:>6.1f}  {elapsed:>6}")

    print()
    return 0


def _run_ci(args) -> int:
    """
    Run quick eval and exit non-zero if:
      - Intelligence Index < CI_MIN_INDEX
      - Any critical metric below CI_BLOCK_THRESHOLDS
    """
    runner = EvalRunner(mode="quick", save_history=True)
    result = runner.run()
    print_report(result)

    if getattr(args, "json", False):
        write_json_report(result)

    exit_code = 0

    if result.intelligence_index < CI_MIN_INDEX:
        print(
            f"\n  ✗ CI FAIL: Intelligence Index {result.intelligence_index:.1f} "
            f"below minimum {CI_MIN_INDEX}",
            file=sys.stderr,
        )
        exit_code = 1

    for metric, threshold in CI_BLOCK_THRESHOLDS.items():
        mr = result.metric_results.get(metric)
        if mr and mr.score < threshold:
            print(
                f"  ✗ CI FAIL: {metric} score {mr.score:.1f} below CI threshold {threshold}",
                file=sys.stderr,
            )
            exit_code = 1

    regressions = result.regression_report.get("regressions", [])
    for reg in regressions:
        if reg["delta"] < -10.0:
            print(
                f"  ✗ CI FAIL: severe regression in {reg['metric']} ({reg['delta']:+.1f})",
                file=sys.stderr,
            )
            exit_code = 1

    if exit_code == 0:
        print(f"\n  ✓ CI PASS — Intelligence Index {result.intelligence_index:.1f}/100")

    return exit_code
