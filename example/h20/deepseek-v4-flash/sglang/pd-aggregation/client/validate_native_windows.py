#!/usr/bin/env python3
"""Bounded-memory trace-window verification, not operator aggregation."""
import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def events(path):
    decoder = json.JSONDecoder()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        buf = ""
        while '"traceEvents"' not in buf:
            chunk = stream.read(65536)
            if not chunk:
                raise ValueError("No traceEvents array")
            buf += chunk
            if len(buf) > 2**20:
                raise ValueError("Unexpected trace header")
        buf = buf[buf.index('"traceEvents"') + len('"traceEvents"'):]
        while "[" not in buf:
            buf += stream.read(65536)
        buf = buf[buf.index("[")+1:]
        eof = False
        while True:
            buf = buf.lstrip(" \r\n\t,")
            if buf.startswith("]"):
                # Consume to EOF so gzip CRC/footer is also verified.
                while stream.read(65536):
                    pass
                return
            try:
                item, end = decoder.raw_decode(buf)
            except json.JSONDecodeError:
                if eof:
                    raise ValueError("Truncated trace JSON")
                chunk = stream.read(65536)
                eof = not chunk
                buf += chunk
                continue
            yield item
            buf = buf[end:]


def summarize(path, phase, role, rank, target):
    tracks = defaultdict(list)
    for event in events(path):
        name = event.get("name", "")
        prefixes = ("step[EXTEND",) if role == "prefill" else (
            "step[DECODE", "step[VERIFY", "step[TARGET_VERIFY")
        if event.get("ph") == "X" and name.startswith(prefixes):
            match = re.search(r"\bbs=(\d+)", name)
            tracks[(event.get("cat"), event.get("pid"), event.get("tid"), name.split(' ')[0])].append(
                int(match.group(1)) if match else None)
    gpu = {k:v for k,v in tracks.items() if k[0] == "gpu_user_annotation"}
    selected = max((gpu or tracks).values(), key=len, default=[])
    sizes = [v for v in selected if v is not None]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "phase": phase, "role": role, "stage": role, "tp_rank": rank,
        "target_steps": target, "captured_steps": len(selected),
        "complete": len(selected) == target,
        "batch_size_min": min(sizes) if sizes else None,
        "batch_size_max": max(sizes) if sizes else None,
        "evidence": "exported native step spans; primary GPU track when available",
        "trace": path.name, "bytes": path.stat().st_size, "sha256": digest,
        "key_averages_enabled": False,
    }


def validate(root, role, tp_size, p_steps=4, d_steps=128):
    records = []
    for phase in ("initial", "after-prerun"):
        stages = ('prefill', 'decode') if role == 'single' else (role,)
        for stage in stages:
            folder = root / phase if role == 'single' else root / phase / stage
            suffix = "EXTEND" if stage == "prefill" else "DECODE"
            for rank in range(tp_size):
                paths = list(folder.glob(f"*-TP-{rank}-{suffix}.trace.json.gz"))
                if len(paths) != 1:
                    raise ValueError(f"Expected exactly one {phase}/{stage}/TP{rank} trace, got {len(paths)}")
                result = summarize(paths[0], phase, stage, rank, p_steps if stage == "prefill" else d_steps)
                result['source_subdir'] = folder.relative_to(root).as_posix()
                result['deployment_role'] = role
                (folder / f"window-{stage}-TP-{rank}.json").write_text(
                    json.dumps(result, indent=2)+"\n", encoding="utf-8")
                records.append(result)
    for stage in (('prefill', 'decode') if role == 'single' else (role,)):
        (root / f"native-validation-{stage}.json").write_text(
            json.dumps([r for r in records if r['role'] == stage], indent=2)+"\n", encoding="utf-8")
    if not all(r["complete"] for r in records):
        raise ValueError("Native trace steps do not match targets; see window summaries")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--role", choices=("prefill", "decode", "single"), required=True)
    parser.add_argument("--tp-size", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.root, args.role, args.tp_size), indent=2))
