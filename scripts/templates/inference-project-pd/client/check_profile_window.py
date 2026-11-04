#!/usr/bin/env python3
"""Fail when a TP rank is missing or the requested decode window is incomplete."""

import argparse
import json
from pathlib import Path


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("profile_dir", type=Path)
parser.add_argument("--tp-size", type=int, required=True)
parser.add_argument("--role", choices=("prefill", "decode"), required=True)
parser.add_argument("--decode-steps", type=int, required=True)
args = parser.parse_args()

files = list(args.profile_dir.rglob("decode-window-TP-*.json"))
records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
expected_ranks = set(range(args.tp_size))
if len(records) != args.tp_size or {record["tp_rank"] for record in records} != expected_ranks:
    raise SystemExit("Missing window summaries. Restart with profile_service.sh or nsys_service.sh.")
if args.role == "prefill":
    valid = all(
        record.get("role") == "prefill"
        and record.get("prefill_scope") == "full"
        and record.get("complete")
        and record.get("prefill_batches", 0) > 0
        for record in records
    )
    if not valid:
        raise SystemExit("Incomplete prefill capture: not all TP ranks recorded the full start/stop window.")
    counts = sorted({record["prefill_batches"] for record in records})
    print(f"Verified: all {args.tp_size} TP ranks captured full prefill; batch counts={counts}.")
else:
    valid = all(
        record.get("role") == "decode"
        and record.get("complete")
        and record.get("decode_steps") == args.decode_steps
        for record in records
    )
    if not valid:
        raise SystemExit(
            f"Incomplete decode capture: not all TP ranks recorded {args.decode_steps} decode_steps."
        )
    print(f"Verified: all {args.tp_size} TP ranks captured {args.decode_steps} decode_steps.")
