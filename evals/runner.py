"""
Main eval runner.

Orchestrates running all benchmark suites, computing metrics,
building the Intelligence Index, and saving history.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from evals.benchmarks import (
    all_scenarios, all_clusters, all_counterfactuals,
    all_personalization_tests, all_adversarial, all_human_judgments,
)
from evals.benchmarks.fault_injection import all_fault_scenarios
from evals.benchmarks.score_calibration import all_calibration_suites
from evals.benchmarks.conflict_detection import all_conflict_scenarios
from evals.benchmarks.mention_popularity_bias import all_bias_scenarios
from evals.benchmarks.nugget_alignment import all_nugget_judgments
from evals.benchmarks.fixture_staleness import load_all_fixture_records
from evals.metrics import (
    RecommendationQualityMetric,
    SemanticConsistencyMetric,
    PersonalizationStrengthMetric,
    CounterfactualSensitivityMetric,
    RetrievalQualityMetric,
    RankingQualityMetric,
    GoldRankingQualityMetric,
    ExplanationIntegrityMetric,
    RobustnessMetric,
    HumanAlignmentMetric,
    StageIsolationMetric,
    ScoreCalibrationMetric,
    ConflictDetectionMetric,
    MentionPopularityBiasMetric,
    NuggetAlignmentMetric,
    FixtureStalenessMetric,
)
from evals.metrics.base import MetricResult
from evals.index import compute_index, compute_index_breakdown
from evals.history import EvalHistory, HistoryRun, get_git_info, make_run_id
from evals.config import QUICK_EVAL_METRICS


@dataclass
class EvalRunResult:
    run_id: str
    mode: str
    timestamp: str
    commit: str
    branch: str
    elapsed_s: float
    intelligence_index: float
    index_breakdown: dict
    metric_results: dict[str, MetricResult]
    scenario_count: int
    pass_rate: float
    regression_report: dict = field(default_factory=dict)


class EvalRunner:
    def __init__(
        self,
        mode: str = "quick",          # "quick" | "full"
        save_history: bool = True,
        pipeline_results: list | None = None,  # for online metrics
    ):
        self.mode = mode
        self.save_history = save_history
        # Online metrics (retrieval_quality, explanation_integrity) need real pipeline output.
        # Prefer live results when provided; otherwise fall back to committed recorded fixtures
        # so these metrics produce REAL, deterministic scores in CI instead of skipping.
        if pipeline_results:
            self.pipeline_results = pipeline_results
        else:
            from evals.benchmarks.recorded import load_recorded_pipeline_results
            self.pipeline_results = load_recorded_pipeline_results()

        self.scenarios = all_scenarios()
        self.clusters = all_clusters()
        self.counterfactuals = all_counterfactuals()
        self.personalization_tests = all_personalization_tests()
        self.adversarial_scenarios = all_adversarial()
        self.human_judgments = all_human_judgments()
        self.fault_scenarios = all_fault_scenarios()
        self.calibration_suites = all_calibration_suites()
        self.conflict_scenarios = all_conflict_scenarios()
        self.bias_scenarios = all_bias_scenarios()
        self.nugget_judgments = all_nugget_judgments()
        self.fixture_records = load_all_fixture_records()

    def run(self) -> EvalRunResult:
        start = time.perf_counter()
        run_id = make_run_id()
        commit, branch = get_git_info()
        timestamp = datetime.now(timezone.utc).isoformat()

        print(f"\n{'='*60}")
        print(f"  ShopSense Intelligence Eval  [{self.mode.upper()} mode]")
        print(f"  Run: {run_id}  |  Commit: {commit}  |  Branch: {branch}")
        print(f"{'='*60}\n")

        metric_results: dict[str, MetricResult] = {}

        # Phase 2: Recommendation Quality
        print("  [Phase 2] Recommendation Quality...")
        result = RecommendationQualityMetric().evaluate(self.scenarios)
        metric_results["recommendation_quality"] = result
        _print_metric_summary(result)

        # Phase 4: Personalization Strength
        print("  [Phase 4] Personalization Strength...")
        result = PersonalizationStrengthMetric().evaluate(self.personalization_tests)
        metric_results["personalization_strength"] = result
        _print_metric_summary(result)

        # Phase 5: Counterfactual Sensitivity
        print("  [Phase 5] Counterfactual Sensitivity...")
        result = CounterfactualSensitivityMetric().evaluate(self.counterfactuals)
        metric_results["counterfactual_sensitivity"] = result
        _print_metric_summary(result)

        # Phase 7: Ranking Quality
        print("  [Phase 7] Ranking Quality...")
        result = RankingQualityMetric().evaluate(self.scenarios)
        metric_results["ranking_quality"] = result
        _print_metric_summary(result)

        # Phase 9: Robustness
        print("  [Phase 9] Robustness...")
        result = RobustnessMetric().evaluate(self.adversarial_scenarios)
        metric_results["robustness"] = result
        _print_metric_summary(result)

        # Phase 10: Stage Fault Injection
        print("  [Phase 10] Stage Fault Injection...")
        result = StageIsolationMetric().evaluate(self.fault_scenarios)
        metric_results["stage_isolation"] = result
        _print_metric_summary(result)

        # Phase 12: Score Calibration
        print("  [Phase 12] Score Calibration...")
        result = ScoreCalibrationMetric().evaluate(self.calibration_suites)
        metric_results["score_calibration"] = result
        _print_metric_summary(result)

        # Phase 13: Conflict Detection
        print("  [Phase 13] Conflict Detection...")
        result = ConflictDetectionMetric().evaluate(self.conflict_scenarios)
        metric_results["conflict_detection"] = result
        _print_metric_summary(result)

        # Phase 14: Mention Popularity Bias
        print("  [Phase 14] Mention Popularity Bias...")
        result = MentionPopularityBiasMetric().evaluate(self.bias_scenarios)
        metric_results["mention_popularity_bias"] = result
        _print_metric_summary(result)

        # Phase 15: Nugget-Based Partial Credit
        print("  [Phase 15] Nugget Alignment...")
        result = NuggetAlignmentMetric().evaluate(self.nugget_judgments)
        metric_results["nugget_alignment"] = result
        _print_metric_summary(result)

        # Phase 16: Fixture Staleness Timestamps
        print("  [Phase 16] Fixture Staleness...")
        result = FixtureStalenessMetric().evaluate(self.fixture_records)
        metric_results["fixture_staleness"] = result
        _print_metric_summary(result)

        if self.mode == "full":
            # Phase 3: Semantic Consistency
            print("  [Phase 3] Semantic Consistency...")
            result = SemanticConsistencyMetric().evaluate(self.clusters)
            metric_results["semantic_consistency"] = result
            _print_metric_summary(result)

            # Phase 6: Retrieval Quality (offline proxy)
            print("  [Phase 6] Retrieval Quality...")
            kwargs = {"pipeline_results": self.pipeline_results} if self.pipeline_results else {}
            result = RetrievalQualityMetric().evaluate(self.scenarios, **kwargs)
            metric_results["retrieval_quality"] = result
            _print_metric_summary(result)

            # Phase 8: Explanation Integrity
            print("  [Phase 8] Explanation Integrity...")
            result = ExplanationIntegrityMetric().evaluate(
                self.scenarios, pipeline_results=self.pipeline_results
            )
            metric_results["explanation_integrity"] = result
            _print_metric_summary(result)

            # Phase 11: Human Alignment (gold rankings)
            print("  [Phase 11] Human Alignment...")
            result = HumanAlignmentMetric().evaluate(self.human_judgments)
            metric_results["human_alignment"] = result
            _print_metric_summary(result)

        elapsed = round(time.perf_counter() - start, 2)

        # Intelligence Index
        index = compute_index(metric_results)
        breakdown = compute_index_breakdown(metric_results)

        # Pass rate across all metric scenarios
        total_scenarios = len(self.scenarios)
        rq = metric_results.get("recommendation_quality")
        passed = rq.details.get("passed", 0) if rq else 0
        pass_rate = round(passed / max(total_scenarios, 1) * 100, 1)

        run_result = EvalRunResult(
            run_id=run_id,
            mode=self.mode,
            timestamp=timestamp,
            commit=commit,
            branch=branch,
            elapsed_s=elapsed,
            intelligence_index=index,
            index_breakdown=breakdown,
            metric_results=metric_results,
            scenario_count=total_scenarios,
            pass_rate=pass_rate,
        )

        if self.save_history:
            history = EvalHistory()
            history_run = HistoryRun(
                run_id=run_id,
                timestamp=timestamp,
                commit=commit,
                branch=branch,
                mode=self.mode,
                intelligence_index=index,
                metric_scores={k: v.score for k, v in metric_results.items()},
                scenario_count=total_scenarios,
                pass_rate=pass_rate,
                elapsed_s=elapsed,
            )
            history.save(history_run)
            run_result.regression_report = history.regression_report(history_run)

        print(f"\n{'='*60}")
        print(f"  Intelligence Index: {index:.1f}/100  [{breakdown['grade']}]")
        print(f"  Scenarios: {total_scenarios}  |  Pass rate: {pass_rate}%  |  {elapsed}s")
        if run_result.regression_report.get("regressions"):
            print("  [REGRESSION DETECTED]")
            for r in run_result.regression_report["regressions"]:
                print(f"    {r['metric']}: {r['delta']:+.1f} ({r['baseline']} -> {r['current']})")
        print(f"{'='*60}\n")

        return run_result


def _print_metric_summary(result: MetricResult) -> None:
    if result.skipped:
        reason = result.details.get("skipped_reason", "not measurable in this run")
        print(f"    [SKIP] {result.name}: {reason}")
        return
    status = "PASS" if result.passed else "FAIL"
    print(f"    [{status}] {result.name}: {result.score:.1f}/100"
          f"  (threshold {result.pass_threshold})"
          f"  [{result.grade}]")
    for f in result.failures[:3]:
        print(f"      ! {f}")
