"""
Pool integrity validator.

Run:  python -m evals.benchmarks.validate_pools

Checks, for every JSON pool in evals/data/pools/:
  1. The file loads without a PoolValidationError (schema + referential integrity).
  2. Every offline scenario's `expected_rank_1` actually matches the deterministic winner
     the scoring engine computes from those weights + product scores. A mismatch means the
     test data is mislabeled (the synthetic math says a different product wins), which would
     silently drag down recommendation_quality. We catch it here instead.
  3. Each scenario's `expected_rank_1_not` products do NOT win.

Exits non-zero on any failure so it can gate CI. Prints a per-pool summary.
"""

from __future__ import annotations

import sys

from evals.engine import build_scored_products
from evals.benchmarks.pool_loader import load_all_pools, PoolValidationError


def validate() -> int:
    try:
        pools = load_all_pools()
    except PoolValidationError as exc:
        print(f"FATAL: {exc}")
        return 1

    if not pools:
        print("No JSON pools found in evals/data/pools/ — nothing to validate.")
        return 0

    total_errors = 0
    for pool in pools:
        category = pool["category"]
        scenarios = pool["scenarios"]
        errors: list[str] = []

        for sc in scenarios:
            scored = build_scored_products(sc.products, sc.rubric_weights)
            if not scored:
                errors.append(f"  {sc.id}: engine returned no scored products")
                continue
            winner = scored[0]["name"]

            if winner != sc.expected_rank_1:
                runner_up = scored[1]["name"] if len(scored) > 1 else "—"
                errors.append(
                    f"  {sc.id}: expected_rank_1={sc.expected_rank_1!r} but engine winner "
                    f"is {winner!r} ({scored[0]['percentage']}% vs runner-up {runner_up})"
                )

            ranking = [s["name"] for s in scored]
            for banned in sc.expected_rank_1_not:
                if ranking and ranking[0] == banned:
                    errors.append(f"  {sc.id}: {banned!r} is in expected_rank_1_not but won")

            for needed in sc.expected_top_2:
                if needed not in ranking[:2]:
                    errors.append(f"  {sc.id}: {needed!r} expected in top-2 but ranked lower")

        status = "OK" if not errors else f"{len(errors)} ERROR(S)"
        print(f"[{category}] {len(scenarios)} scenarios, {len(pool['human_judgments'])} judgments — {status}")
        for e in errors:
            print(e)
        total_errors += len(errors)

    print()
    if total_errors:
        print(f"FAILED: {total_errors} integrity error(s) across pools.")
        return 1
    print(f"PASSED: all {len(pools)} pools are internally consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
