"""Offline tuning comparisons do not change services or benchmark protocols."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("tuning_comparison", Path(__file__).resolve().parents[1] / "compare_tuning_benchmarks.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.old = {"conditions": {"model": "checkpoint", "resource_budget": {"cards": 4},
                                  "workload": {"C": 16}, "measurement": {"scope": "end-to-end"}},
                    "profiler_enabled": False, "variant": "baseline", "design": {"TP": 4},
                    "runs": [{"total": 80, "successful": 80, "metrics": {"throughput": 100, "latency_ms": 10}}]}
        self.new = copy.deepcopy(self.old)
        self.new.update(variant="joint", design={"TP": 2, "kernel": "candidate"})
        self.new["runs"][0]["metrics"] = {"throughput": 120, "latency_ms": 9}

    def compare(self, **kwargs):
        return module.compare(self.old, self.new, kwargs.pop("objective", "throughput"),
                              kwargs.pop("direction", "higher"), kwargs.pop("minimum", 5), **kwargs)

    def test_joint_design_changes_allowed(self):
        result = self.compare()
        self.assertEqual(result["verdict"], "observed_improvement")
        self.assertTrue(result["single_observation"])
        self.assertAlmostEqual(result["objective"]["improvement_pct"], 20)

    def test_lower_metric(self):
        self.assertAlmostEqual(self.compare(objective="latency_ms", direction="lower")["objective"]["improvement_pct"], 10)

    def test_guardrail_failure(self):
        self.new["runs"][0]["metrics"]["latency_ms"] = 20
        self.assertEqual(self.compare(guardrails=[("latency_ms", "lower", 5)])["verdict"], "guardrail_failed")

    def test_below_threshold(self):
        self.assertEqual(self.compare(minimum=30)["verdict"], "below_threshold")

    def test_conditions_mismatch_rejected(self):
        self.new["conditions"]["workload"]["C"] = 1
        with self.assertRaises(ValueError): self.compare()

    def test_failed_requests_rejected(self):
        self.new["runs"][0]["successful"] = 79
        with self.assertRaises(ValueError): self.compare()

    def test_profiled_measurements_rejected(self):
        self.new["profiler_enabled"] = True
        with self.assertRaises(ValueError): self.compare()

    def test_invalid_metrics_rejected(self):
        for value in (float("nan"), float("inf"), -1, True):
            self.new["runs"][0]["metrics"]["throughput"] = value
            with self.assertRaises(ValueError): self.compare()

    def test_zero_baseline_and_missing_metric(self):
        self.old["runs"][0]["metrics"]["throughput"] = 0
        with self.assertRaises(ValueError): self.compare()
        with self.assertRaises(ValueError): self.compare(objective="unknown")

    def test_multiple_runs_median(self):
        self.new["runs"].append(copy.deepcopy(self.new["runs"][0]))
        self.new["runs"][1]["metrics"]["throughput"] = 140
        self.assertEqual(self.compare()["objective"]["candidate_median"], 130)


if __name__ == "__main__":
    unittest.main()
