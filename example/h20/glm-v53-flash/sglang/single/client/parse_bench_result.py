#!/usr/bin/env python3
"""Parse benchmark JSON/JSONL files into the table used by the example."""

import argparse
import glob
import json
import os


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("result_dir")
parser.add_argument("--device-count", type=int, required=True)
args = parser.parse_args()
if args.device_count <= 0:
    parser.error("--device-count must be positive")

files = sorted(
    glob.glob(os.path.join(args.result_dir, "*concurrency*.json"))
    + glob.glob(os.path.join(args.result_dir, "*concurrency*.jsonl"))
)
if not files:
    raise SystemExit(f"No benchmark JSON/JSONL files found in: {args.result_dir}")

records = []
for path in files:
    with open(path, "r", encoding="utf-8") as stream:
        if path.endswith(".jsonl"):
            records.extend((path, json.loads(line)) for line in stream if line.strip())
        else:
            records.append((path, json.load(stream)))
if not records:
    raise SystemExit(f"Benchmark result files are empty: {args.result_dir}")

rows = []
for path, data in records:
    filename = os.path.basename(path)
    concurrency = int(filename.split("concurrency", 1)[1].split(".", 1)[0])
    total = data.get("total_throughput", data.get("total_token_throughput"))
    output = data["output_throughput"]
    rows.append(
        {
            "concurrency": concurrency,
            "total_tok": total,
            "output_tok": output,
            "tps_gpu": output / args.device_count,
            "mean_ttft": data["mean_ttft_ms"],
            "p50_ttft": data.get("median_ttft_ms", data.get("p50_ttft_ms")),
            "p99_ttft": data["p99_ttft_ms"],
            "mean_tpot": data["mean_tpot_ms"],
            "p50_tpot": data.get("median_tpot_ms", data.get("p50_tpot_ms")),
            "p99_tpot": data["p99_tpot_ms"],
            "success": data["completed"],
        }
    )
rows.sort(key=lambda row: row["concurrency"])

table = [
    "| Maximum request concurrency | Total token throughput (tok/s) | Output token throughput (tok/s) | TPS/GPU | Mean TTFT (ms) | P50 TTFT (ms) | P99 TTFT (ms) | Mean TPOT (ms) | P50 TPOT (ms) | P99 TPOT (ms) | Successful requests |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for row in rows:
    table.append(
        f"| {row['concurrency']} | {row['total_tok']:.2f} | {row['output_tok']:.2f} "
        f"| {row['tps_gpu']:.2f} | {row['mean_ttft']:.2f} | {row['p50_ttft']:.2f} "
        f"| {row['p99_ttft']:.2f} | {row['mean_tpot']:.2f} | {row['p50_tpot']:.2f} "
        f"| {row['p99_tpot']:.2f} | {row['success']} |"
    )
markdown = "\n".join(table)
print(markdown)
output = os.path.join(args.result_dir, "benchmark_summary.md")
with open(output, "w", encoding="utf-8") as stream:
    stream.write(markdown + "\n")
print(f"\nSaved:\n{output}")
