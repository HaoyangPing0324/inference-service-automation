#!/usr/bin/env python3
"""Summarize PyTorch Chrome traces without loading the full JSON into memory.

The generated CPU table resembles ``prof.key_averages().table()``.  Inclusive
times and call counts come directly from trace events.  Self CPU time is
reconstructed from nested CPU intervals and is therefore labelled approximate;
save the native key_averages table during capture when exact PyTorch semantics
are required.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import ijson


CPU_CATEGORIES = {"cpu_op", "user_annotation"}
PYTHON_CATEGORIES = {"python_function"}
GPU_CATEGORIES = {"kernel", "gpu_memcpy", "gpu_memset"}


@dataclass(slots=True)
class Interval:
    start: float
    end: float
    name: str
    category: str


def open_trace(path: Path):
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def iter_events(path: Path) -> Iterable[dict]:
    with open_trace(path) as stream:
        yield from ijson.items(stream, "traceEvents.item")


def add_stat(stats: dict, key: tuple[str, str], duration_us: float) -> None:
    row = stats[key]
    row["calls"] += 1
    row["total_us"] += duration_us
    row["max_us"] = max(row["max_us"], duration_us)


def union_length(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    intervals.sort()
    total = 0.0
    left, right = intervals[0]
    for start, end in intervals[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def approximate_self_times(by_thread: dict[tuple, list[Interval]]) -> Counter:
    self_us: Counter = Counter()
    for events in by_thread.values():
        events.sort(key=lambda item: (item.start, -item.end))
        stack: list[dict] = []
        for event in events:
            while stack and event.start >= stack[-1]["event"].end:
                finished = stack.pop()
                own = finished["event"].end - finished["event"].start
                self_us[(finished["event"].category, finished["event"].name)] += max(
                    0.0, own - union_length(finished["children"])
                )
            while stack and event.end > stack[-1]["event"].end:
                finished = stack.pop()
                own = finished["event"].end - finished["event"].start
                self_us[(finished["event"].category, finished["event"].name)] += max(
                    0.0, own - union_length(finished["children"])
                )
            if stack:
                stack[-1]["children"].append((event.start, event.end))
            stack.append({"event": event, "children": []})
        while stack:
            finished = stack.pop()
            own = finished["event"].end - finished["event"].start
            self_us[(finished["event"].category, finished["event"].name)] += max(
                0.0, own - union_length(finished["children"])
            )
    return self_us


def analyze(path: Path) -> dict:
    stats = defaultdict(lambda: {"calls": 0, "total_us": 0.0, "max_us": 0.0})
    categories: Counter = Counter()
    cpu_intervals: dict[tuple, list[Interval]] = defaultdict(list)
    gpu_intervals: list[tuple[float, float]] = []
    gpu_phase_durations: dict[str, dict[tuple, list[float]]] = {
        "decode": defaultdict(list),
        "prefill": defaultdict(list),
    }
    trace_start = None
    trace_end = None

    for event in iter_events(path):
        if event.get("ph") != "X" or "dur" not in event:
            continue
        try:
            start = float(event["ts"])
            duration = float(event["dur"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration < 0:
            continue
        category = str(event.get("cat", "uncategorized"))
        name = str(event.get("name", "<unnamed>"))
        categories[category] += 1
        add_stat(stats, (category, name), duration)
        trace_start = start if trace_start is None else min(trace_start, start)
        trace_end = start + duration if trace_end is None else max(trace_end, start + duration)

        if category in CPU_CATEGORIES:
            cpu_intervals[(event.get("pid"), event.get("tid"))].append(
                Interval(start, start + duration, name, category)
            )
        if category in GPU_CATEGORIES:
            gpu_intervals.append((start, start + duration))
        if category == "gpu_user_annotation":
            track = (event.get("pid"), event.get("tid"))
            if name.startswith("step[DECODE"):
                gpu_phase_durations["decode"][track].append(duration)
            elif name.startswith("step[EXTEND"):
                gpu_phase_durations["prefill"][track].append(duration)

    self_times = approximate_self_times(cpu_intervals)
    rows = []
    for (category, name), values in stats.items():
        calls = values["calls"]
        rows.append(
            {
                "category": category,
                "name": name,
                "calls": calls,
                "total_us": values["total_us"],
                "avg_us": values["total_us"] / calls,
                "max_us": values["max_us"],
                "approx_self_us": self_times.get((category, name), 0.0),
            }
        )
    def primary_phase_track(phase: str) -> list[float]:
        tracks = gpu_phase_durations[phase]
        if not tracks:
            return []
        # An annotation can be projected onto several CUDA streams.  Use the
        # track with the most steps, then the greatest total duration; this
        # selects the main/critical-path stream without hard-coding a stream id.
        return max(tracks.values(), key=lambda values: (len(values), sum(values)))

    return {
        "file": str(path),
        "trace_span_us": 0.0 if trace_start is None else trace_end - trace_start,
        "gpu_busy_us": union_length(gpu_intervals),
        "categories": dict(categories),
        "rows": rows,
        "gpu_decode_us": primary_phase_track("decode"),
        "gpu_prefill_us": primary_phase_track("prefill"),
    }


def top_rows(result: dict, categories: set[str], sort_key: str, limit: int) -> list[dict]:
    rows = [row for row in result["rows"] if row["category"] in categories]
    return sorted(rows, key=lambda row: row[sort_key], reverse=True)[:limit]


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["category", "name", "calls", "total_us", "avg_us", "max_us", "approx_self_us"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict], self_cpu: bool = False) -> str:
    if self_cpu:
        header = "| Name | Category | Calls | Approx Self CPU (ms) | CPU total (ms) | CPU avg (us) |\n|---|---:|---:|---:|---:|---:|"
    else:
        header = "| Name | Category | Calls | Total (ms) | Avg (us) | Max (us) |\n|---|---:|---:|---:|---:|---:|"
    lines = [header]
    for row in rows:
        name = row["name"].replace("|", "\\|")
        if self_cpu:
            lines.append(
                f"| {name} | {row['category']} | {row['calls']} | "
                f"{row['approx_self_us'] / 1000:.3f} | {row['total_us'] / 1000:.3f} | {row['avg_us']:.3f} |"
            )
        else:
            lines.append(
                f"| {name} | {row['category']} | {row['calls']} | "
                f"{row['total_us'] / 1000:.3f} | {row['avg_us']:.3f} | {row['max_us']:.3f} |"
            )
    return "\n".join(lines)


def find_traces(inputs: list[str]) -> list[Path]:
    found = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            found.extend(path.rglob("*.trace.json.gz"))
            found.extend(path.rglob("*.trace.json"))
        elif path.is_file():
            found.append(path)
    return sorted(set(found))


def rank_row(trace: Path, result: dict) -> dict:
    rank_match = re.search(r"TP-(\d+)", trace.name)
    by_name = {(row["category"], row["name"]): row for row in result["rows"]}
    decode_us = sorted(result["gpu_decode_us"])
    prefill_us = result["gpu_prefill_us"]

    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        return values[math.ceil(fraction * len(values)) - 1]
    kernels = [row for row in result["rows"] if row["category"] == "kernel"]
    communication = [
        row for row in kernels
        if "nccl" in row["name"].lower() or "all_reduce" in row["name"].lower()
    ]
    main_kernel = by_name.get(("kernel", "main_kernel"), {})
    span = result["trace_span_us"]
    return {
        "rank": int(rank_match.group(1)) if rank_match else trace.name,
        "trace_span_ms": span / 1000,
        "gpu_busy_ms": result["gpu_busy_us"] / 1000,
        "gpu_time_util_pct": 100 * result["gpu_busy_us"] / span if span else 0,
        "decode_calls": len(decode_us),
        "decode_avg_ms": (sum(decode_us) / len(decode_us) / 1000) if decode_us else 0,
        "decode_p50_ms": percentile(decode_us, 0.50) / 1000,
        "decode_p99_ms": percentile(decode_us, 0.99) / 1000,
        "prefill_calls": len(prefill_us),
        "prefill_total_ms": sum(prefill_us) / 1000,
        "kernel_launches": sum(row["calls"] for row in kernels),
        "kernel_sum_ms": sum(row["total_us"] for row in kernels) / 1000,
        "main_kernel_ms": main_kernel.get("total_us", 0) / 1000,
        "communication_kernel_ms": sum(row["total_us"] for row in communication) / 1000,
    }


def write_rank_comparison(output_dir: Path, rows: list[dict]) -> None:
    rows.sort(key=lambda row: row["rank"] if isinstance(row["rank"], int) else 10**9)
    csv_path = output_dir / "rank-comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# TP rank comparison",
        "",
        "> GPU time utilization is the union of GPU activity intervals divided by the full trace span. Kernel sums can exceed wall time when streams overlap.",
        "",
        "| TP | Span ms | GPU busy ms | GPU time util | Decode calls | Decode avg ms | Decode P50 ms | Decode P99 ms | Prefill calls | Prefill total ms | Kernel launches | Kernel sum ms | main_kernel ms | Communication kernels ms |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['trace_span_ms']:.3f} | {row['gpu_busy_ms']:.3f} | "
            f"{row['gpu_time_util_pct']:.2f}% | {row['decode_calls']} | {row['decode_avg_ms']:.3f} | "
            f"{row['decode_p50_ms']:.3f} | {row['decode_p99_ms']:.3f} | "
            f"{row['prefill_calls']} | {row['prefill_total_ms']:.3f} | {row['kernel_launches']} | "
            f"{row['kernel_sum_ms']:.3f} | {row['main_kernel_ms']:.3f} | {row['communication_kernel_ms']:.3f} |"
        )
    (output_dir / "rank-comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Trace file(s) or a directory containing traces")
    parser.add_argument("--output-dir", type=Path, default=Path("profiling_results/torch_trace_summary"))
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    traces = find_traces(args.inputs)
    if not traces:
        parser.error("no .trace.json or .trace.json.gz files found")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    index_lines = ["# Torch trace summaries", ""]
    rank_rows = []
    for trace in traces:
        print(f"Analyzing {trace} ...", flush=True)
        result = analyze(trace)
        rank_rows.append(rank_row(trace, result))
        stem = trace.name.removesuffix(".trace.json.gz").removesuffix(".trace.json")
        all_rows = sorted(result["rows"], key=lambda row: row["total_us"], reverse=True)
        cpu = top_rows(result, CPU_CATEGORIES, "approx_self_us", args.limit)
        python_rows = top_rows(result, PYTHON_CATEGORIES, "total_us", args.limit)
        gpu = top_rows(result, GPU_CATEGORIES, "total_us", args.limit)
        write_csv(args.output_dir / f"{stem}-all-events.csv", all_rows)

        report = [
            f"# {trace.name}",
            "",
            f"Trace span: {result['trace_span_us'] / 1000:.3f} ms",
            "",
            "## CPU operations (key_averages-like)",
            "",
            "> Approx Self CPU is reconstructed from nested trace intervals; it is not the native PyTorch key_averages value.",
            "",
            markdown_table(cpu, self_cpu=True),
            "",
            "## Python call hotspots",
            "",
            "> Inclusive totals may double-count nested calls; use this table for navigation, not wall-time accounting.",
            "",
            markdown_table(python_rows),
            "",
            "## GPU activities",
            "",
            "> Total is the sum of event durations and may exceed wall time when streams overlap.",
            "",
            markdown_table(gpu),
            "",
            "## Event categories",
            "",
            "```json",
            json.dumps(result["categories"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
        report_path = args.output_dir / f"{stem}-summary.md"
        report_path.write_text("\n".join(report), encoding="utf-8")
        index_lines.append(f"- [{trace.name}]({report_path.name})")

    write_rank_comparison(args.output_dir, rank_rows)
    index_lines.extend(["", "- [TP rank comparison](rank-comparison.md)"])
    (args.output_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(traces)} summaries to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
