"""Compare normalized benchmark observations offline; never launch workloads."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return value


def validate(data):
    if data.get("profiler_enabled") is not False:
        raise ValueError("profiler_enabled must explicitly be false")
    conditions = data.get("conditions")
    if not isinstance(conditions, dict) or any(not conditions.get(key) for key in ("model", "resource_budget", "workload", "measurement")):
        raise ValueError("conditions must include model, resource_budget, workload and measurement")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("runs must be a nonempty list")
    for run in runs:
        total, successful = run.get("total"), run.get("successful")
        if type(total) is not int or total <= 0 or type(successful) is not int or successful != total:
            raise ValueError("each run must have positive total and all requests successful")
        if not isinstance(run.get("metrics"), dict):
            raise ValueError("each run needs metrics")
        for key, value in run["metrics"].items():
            number(value, key)
    return conditions, runs


def metric_change(baseline, candidate, metric, direction):
    if direction not in ("higher", "lower"):
        raise ValueError("direction must be higher or lower")
    try:
        old_values = [run["metrics"][metric] for run in baseline]
        new_values = [run["metrics"][metric] for run in candidate]
    except KeyError as exc:
        raise ValueError(f"missing metric: {metric}") from exc
    old, new = median(old_values), median(new_values)
    if old <= 0:
        raise ValueError(f"baseline {metric} must be positive for percentage comparison")
    improvement = (new - old) / old * 100 * (1 if direction == "higher" else -1)
    return {"metric": metric, "direction": direction, "baseline_median": old,
            "candidate_median": new, "baseline_range": [min(old_values), max(old_values)],
            "candidate_range": [min(new_values), max(new_values)], "improvement_pct": improvement}


def compare(baseline, candidate, objective, direction, minimum, guardrails=()):
    number(minimum, "minimum improvement")
    old_conditions, old_runs = validate(baseline)
    new_conditions, new_runs = validate(candidate)
    if old_conditions != new_conditions:
        raise ValueError("conditions differ; resolve comparability before calculating benefit")
    if len({run["total"] for run in old_runs + new_runs}) != 1:
        raise ValueError("request totals differ")
    result = metric_change(old_runs, new_runs, objective, direction)
    checks = []
    for metric, guard_direction, tolerance in guardrails:
        number(tolerance, "guardrail tolerance")
        check = metric_change(old_runs, new_runs, metric, guard_direction)
        check.update(max_regression_pct=tolerance, passed=check["improvement_pct"] >= -tolerance)
        checks.append(check)
    passed = result["improvement_pct"] >= minimum
    guards_passed = all(check["passed"] for check in checks)
    return {"baseline": baseline.get("variant"), "candidate": candidate.get("variant"),
            "run_counts": [len(old_runs), len(new_runs)], "objective": result,
            "min_improvement_pct": minimum, "objective_passed": passed, "guardrails": checks,
            "verdict": "guardrail_failed" if not guards_passed else "observed_improvement" if passed else "below_threshold",
            "limitations": "Observed measurements only; no statistical significance or per-layer causality established.",
            "single_observation": len(old_runs) == 1 or len(new_runs) == 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--direction", required=True, choices=("higher", "lower"))
    parser.add_argument("--min-improvement-pct", required=True, type=float)
    parser.add_argument("--guardrail", action="append", default=[], metavar="METRIC:DIRECTION:MAX_REGRESSION_PCT")
    args = parser.parse_args()
    try:
        guardrails = []
        for value in args.guardrail:
            metric, direction, tolerance = value.split(":")
            guardrails.append((metric, direction, float(tolerance)))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        print(json.dumps(compare(baseline, candidate, args.objective, args.direction,
                                 args.min_improvement_pct, guardrails), ensure_ascii=False, indent=2))
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
