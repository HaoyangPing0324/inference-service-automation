#!/usr/bin/env python3
"""Validate a native mixed time trace on its source host; no operator aggregation.

Uses native trace event names, not configured P/D targets. Unknown/missing stage
markers fail coverage validation rather than inventing a step count.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from collections import defaultdict



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

def validate_workload(workload):
    if (workload.get("protocol") != "time" or workload.get("status") != "captured-unvalidated"
        or workload.get("failure") or workload.get("warmup_requests") != 2
        or not workload.get("issued") or workload.get("issued") != workload.get("completed")
        or workload.get("successful") != workload.get("completed")):
        raise ValueError("Time workload failed, is incomplete, or has mismatched request counts")
    controls = workload.get("controls", [])
    starts = [r for r in controls if r.get("action") == "start"]
    stops = [r for r in controls if r.get("action") == "stop"]
    identities = {(r.get("role"), r.get("endpoint", "").rsplit("/", 1)[0]) for r in starts}
    stopped = {(r.get("role"), r.get("endpoint", "").rsplit("/", 1)[0]) for r in stops}
    roles = {r[0] for r in identities}
    if (roles not in ({"single"}, {"prefill", "decode"}) or not starts or identities != stopped
        or len(starts) != len(identities) or len(stops) != len(starts)
        or not all(r.get("success") is True for r in starts + stops)):
        raise ValueError("Missing, duplicated or unsuccessful time profile controls")
    duration = workload.get("control_common_interval_seconds")
    requested = workload.get("capture_seconds")
    if (not isinstance(duration, (int, float)) or not isinstance(requested, (int, float))
        or not math.isfinite(duration) or not math.isfinite(requested) or duration < requested or requested <= 0):
        raise ValueError("Control common interval is shorter than the requested capture")
    try:
        measured = min(r["sent_monotonic"] for r in stops) - max(r["received_monotonic"] for r in starts)
    except (KeyError, TypeError):
        raise ValueError("Missing client monotonic control brackets") from None
    if not math.isfinite(measured) or measured < requested or not math.isclose(duration, measured, abs_tol=1e-6):
        raise ValueError("Stored duration does not match actual control brackets")
    events = workload.get("events", [])
    def one(kind):
        matches = [e for e in events if e.get("event") == kind]
        if len(matches) != 1:
            raise ValueError(f"Missing/duplicate middle-window event: {kind}")
        return matches[0]
    c = workload.get("C", 0)
    pre = workload.get("prerun_completed_multiplier", 0)
    post = workload.get("postrun_completed_multiplier", 0)
    if (not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (c, pre, post))
        or one("capture-started").get("completed", 0) < pre*c
        or one("postrun-complete").get("completed", 0) < one("capture-stopped").get("completed", 0) + post*c):
        raise ValueError("Missing C-dependent prerun/postrun load around the middle window")
    if any(r.get("body", {}).get("profile_by_stage") is not False
           or "num_steps" in r.get("body", {}) for r in starts):
        raise ValueError("Time capture must use continuous mixed native controls")
    return roles


def summarize(path, role, rank):
    tracks = defaultdict(int)
    sizes = defaultdict(list)
    event_count = gpu_events = 0
    for event in events(path):
        event_count += 1
        category = event.get("cat", "")
        if category in ("kernel", "gpu_memcpy", "gpu_memset"):
            gpu_events += 1
        name = event.get("name", "")
        match = re.match(r"step\[(EXTEND|DECODE|VERIFY|TARGET_VERIFY)\b", name)
        if event.get("ph") != "X" or not match:
            continue
        stage = "prefill" if match[1] == "EXTEND" else "decode"
        key = (stage, category, event.get("pid"), event.get("tid"), match[1])
        tracks[key] += 1
        batch = re.search(r"\bbs=(\d+)", name)
        if batch:
            sizes[key].append(int(batch[1]))
    stages = {}
    for stage in ("prefill", "decode"):
        keys = [k for k in tracks if k[0] == stage]
        gpu = [k for k in keys if k[1] == "gpu_user_annotation"]
        primary = max(gpu or keys, key=lambda k: tracks[k], default=None)
        batch = sizes[primary] if primary is not None else []
        stages[stage] = {"steps": tracks[primary] if primary is not None else 0,
                         "batch_size_min": min(batch) if batch else None,
                         "batch_size_max": max(batch) if batch else None}
    required = ("prefill", "decode") if role == "single" else (role,)
    coverage = all(stages[s]["steps"] > 0 for s in required)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"protocol": "time", "phase": "capture", "role": role, "tp_rank": rank,
            "complete": bool(event_count and gpu_events and coverage),
            "stage_coverage": coverage, "stages": stages, "event_count": event_count,
            "gpu_event_count": gpu_events, "trace": path.name, "bytes": path.stat().st_size,
            "sha256": digest,
            "key_averages_enabled": False,
            "evidence": "native primary step track per stage; no fixed step target"}


def validate(root, role, tp_size, workload):
    roles = validate_workload(workload)
    if role not in roles or tp_size < 1 or workload.get("mode") != "torch":
        raise ValueError("Role, TP size or tool mismatch")
    folder = root / "capture" / role
    records = []
    for rank in range(tp_size):
        pattern = re.compile(rf"(?:^|-)TP-{rank}(?:\.|-)")
        paths = [p for p in folder.glob("*.trace.json.gz") if pattern.search(p.name)]
        if len(paths) != 1:
            raise ValueError(f"Expected one mixed trace for {role}/TP-{rank}, got {len(paths)}")
        record = summarize(paths[0], role, rank)
        record["source_subdir"] = f"capture/{role}"
        records.append(record)
        (folder / f"window-TP-{rank}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (root / f"time-validation-{role}.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    if not all(r["complete"] for r in records):
        raise ValueError("Empty GPU trace or missing stage coverage; see summaries; do not increase budget automatically")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--role", choices=("single", "prefill", "decode"), required=True)
    parser.add_argument("--tp-size", type=int, required=True)
    parser.add_argument("--workload", type=Path, help="Verified workload.json copied from the client host")
    args = parser.parse_args()
    workload = json.loads((args.workload or args.root / "workload.json").read_text(encoding="utf-8"))
    print(json.dumps(validate(args.root, args.role, args.tp_size, workload), indent=2))
