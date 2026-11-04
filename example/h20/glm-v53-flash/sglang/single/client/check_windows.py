#!/usr/bin/env python3
"""Validate bounded windows on the actual source host, not an empty shadow role."""
import argparse
import json
from pathlib import Path


def validate(root, tp_size, role, prefill_steps=4, decode_steps=128):
    errors, records = [], []
    stages = ("prefill", "decode") if role == "single" else (role,)
    for phase in ("initial", "after-prerun"):
        for stage in stages:
            directory = root / phase / stage
            target = prefill_steps if stage == "prefill" else decode_steps
            for rank in range(tp_size):
                path = directory / f"window-{stage}-TP-{rank}.json"
                if not path.is_file():
                    errors.append(f"Missing {path}")
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                records.append(record)
                if (record.get("phase") != phase or record.get("stage") != stage
                    or record.get("role") not in (role, stage) or record.get("tp_rank") != rank
                    or record.get("captured_steps") != target
                    or record.get("target_steps") != target or not record.get("complete")):
                    errors.append(f"Incomplete/mismatched window: {path}")
                suffix = "EXTEND" if stage == "prefill" else "DECODE"
                traces = list(directory.glob(f"*-TP-{rank}-{suffix}.trace.json.gz"))
                traces += list(directory.glob(f"TP-{rank}.trace.json.gz"))
                if len(traces) != 1 or traces[0].stat().st_size == 0:
                    errors.append(f"Missing/duplicate trace for {phase}/{stage}/TP-{rank}")
                if record.get("key_averages_enabled"):
                    files = record.get("key_averages_files", [])
                    if record.get("key_averages_error") or len(files) != 2 or any(
                        not (directory / name).is_file() for name in files):
                        errors.append(f"Missing native averages: {path}")
    if errors:
        raise ValueError("\n".join(errors))
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--tp-size", type=int, required=True)
    parser.add_argument("--role", choices=("prefill", "decode", "single"), required=True)
    parser.add_argument("--prefill-steps", type=int, default=4)
    parser.add_argument("--decode-steps", type=int, default=128)
    args = parser.parse_args()
    records = validate(args.root, args.tp_size, args.role, args.prefill_steps, args.decode_steps)
    print(json.dumps({"valid": True, "windows": records}, indent=2))
