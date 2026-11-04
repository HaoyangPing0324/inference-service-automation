#!/usr/bin/env python3
"""Recover verified native single-service or PD windows through SSH aliases.

Runs on any caller OS with Python 3.11+ and OpenSSH. Remote hosts are Linux.
No framework, model, or SSH topology is inferred by this collector.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


def collect_time(args, owner, output, target, remote, workload):
    """Recover whole mixed traces; never split a single-service time window by stage."""
    spec = importlib.util.spec_from_file_location("time_validation", Path(__file__).parent /
                                                "templates/shared/client/validate_time_window.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    roles = validator.validate_workload(workload)
    if workload.get("mode") != "torch" or workload.get("C") != args.concurrency:
        raise ValueError("Time workload tool/concurrency mismatch")
    if roles == {"single"}:
        if args.prefill_host != args.decode_host:
            raise ValueError("Single time trace must originate on one host")
        sources = [("single", args.prefill_host, args.tp_size)]
    else:
        sources = [("prefill", args.prefill_host, getattr(args, "prefill_tp_size", None) or args.tp_size),
                   ("decode", args.decode_host, getattr(args, "decode_tp_size", None) or args.tp_size)]
    stage = Path(tempfile.mkdtemp(prefix=f".C{args.concurrency}-", dir=output))
    manifest = []
    try:
        for role, host, tp in sources:
            records = json.loads(remote_text(host, remote / f"time-validation-{role}.json"))
            if (len(records) != tp or {r.get("tp_rank") for r in records} != set(range(tp))):
                raise ValueError(f"Missing/duplicate time ranks for {role}")
            for r in records:
                name = r.get("trace", "")
                if (r.get("protocol") != "time" or r.get("role") != role
                    or r.get("phase") != "capture" or r.get("complete") is not True
                    or r.get("source_subdir") != f"capture/{role}"
                    or PurePosixPath(name).name != name or name in ("", ".", "..")
                    or "\\" in name):
                    raise ValueError("Invalid time trace record")
                source = remote / f"capture/{role}" / name
                folder = stage / "capture" / role
                folder.mkdir(parents=True, exist_ok=True)
                dest = folder / f"TP-{r['tp_rank']}.trace.json.gz"
                fetch(host, source, dest)
                with dest.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if dest.stat().st_size != r["bytes"] or digest != r["sha256"]:
                    raise ValueError(f"Size/hash mismatch: {dest}")
                # Independently recheck gzip/JSON, GPU activity and P/D coverage.
                # Add only this known template directory for the streaming reader.
                import sys
                native_dir = str(Path(__file__).parent / "templates/inference-project/client")
                sys.path.insert(0, native_dir)
                try:
                    local = validator.summarize(dest, role, r["tp_rank"])
                finally:
                    sys.path.remove(native_dir)
                if not local["complete"]:
                    raise ValueError(f"Local trace lacks required stage/GPU coverage: {dest}")
                summary = {**local, "source_host": host, "source_trace": name,
                           "source_path": str(source), "local_path": dest.relative_to(stage).as_posix()}
                (folder / f"window-TP-{r['tp_rank']}.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
                manifest.append(summary)
        (stage / "workload.json").write_text(json.dumps(workload, indent=2)+"\n", encoding="utf-8")
        text = (f"# Time Profiler C{args.concurrency}\n\nRun: `{args.run}`. "
                f"Result owner: `{owner.relative_to(args.project.resolve()).as_posix()}`. "
                f"Prerun >= {workload['prerun_completed_multiplier']}*C completions "
                f"and >= {workload['prerun_seconds']}s; capture {workload['capture_seconds']}s; "
                f"postrun >= {workload['postrun_completed_multiplier']}*C completions after stop. "
                f"Successful formal requests: {workload['successful']}; warmup=2; "
                "continuously replenished load; no fixed P/D step target.\n\n"
                "Control intervals use the client clock; GPU clocks are not proven aligned. "
                "All mixed traces passed local stage coverage, gzip, size and SHA-256 checks.\n\n"
                "```json\n" + json.dumps(manifest, indent=2) + "\n```\n")
        (stage / "MANIFEST.md").write_text(text, encoding="utf-8")
        backup = None
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".C{args.concurrency}-previous-", dir=output))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            if backup is not None:
                os.replace(backup, target)
            raise
        # Keep the previous validated directory as a recoverable sibling.
        print(f"Delivered {len(manifest)} mixed traces: {target}", flush=True)
        return target
    except Exception:
        print(f"Partial staging preserved for diagnosis: {stage}", flush=True)
        raise


def remote_text(host, path):
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", host, "cat -- " + shlex.quote(str(path))],
        text=True, encoding="utf-8")


def fetch(host, source, destination):
    subprocess.run(["scp", "-O", "-o", "BatchMode=yes",
                    f"{host}:{shlex.quote(str(source))}", str(destination)], check=True)


def resolve_result_owner(project, relative=None):
    """Scope a tuning capture to one existing study/version; never infer a version."""
    project = project.resolve(strict=True)
    if relative is None:
        return project
    value = str(relative)
    parts = value.split("/")
    valid_shape = ((len(parts) == 3 and parts[2] == "baseline") or
                   (len(parts) == 4 and parts[2] == "candidates"))
    if (not valid_shape or parts[0] != "tuning" or "\\" in value or
        any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", p) for p in parts)):
        raise ValueError("Result owner must be tuning/<study>/baseline or tuning/<study>/candidates/<id>")
    owner = project
    for part in parts:
        owner = owner / part
        if owner.is_symlink():
            raise ValueError("Result owner cannot contain a symlink")
    expected_owner = owner
    owner = owner.resolve(strict=True)
    if owner != expected_owner:
        raise ValueError("Result owner must not redirect to another version")
    if not owner.is_dir() or not owner.is_relative_to(project):
        raise ValueError("Result owner must be an existing version inside the experiment")
    return owner


def collect(args):
    if (isinstance(args.concurrency, bool) or not isinstance(args.concurrency, int) or args.concurrency < 1
        or isinstance(args.tp_size, bool) or not isinstance(args.tp_size, int) or args.tp_size < 1):
        raise ValueError("Concurrency and TP size must be positive integers")
    if not isinstance(args.run, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.run):
        raise ValueError("Invalid run identifier")
    remote_root = PurePosixPath(args.remote_project)
    if not remote_root.is_absolute() or ".." in remote_root.parts or "\\" in args.remote_project:
        raise ValueError("Remote project must be an absolute normalized POSIX path")
    project = args.project.resolve(strict=True)
    owner = resolve_result_owner(project, getattr(args, "result_owner", None))
    output = owner / "profiling_results" / "profiler"
    target = output / f"C{args.concurrency}"
    if not output.resolve().is_relative_to(owner) or target.is_symlink():
        raise ValueError("Result target must stay inside the experiment, without a C-directory symlink")
    output.mkdir(parents=True, exist_ok=True)
    if target.exists() and not args.replace:
        raise ValueError("Existing C result; use --replace only with authorization")
    remote = PurePosixPath(args.remote_project) / "server" / "profiles" / args.run
    client_host = getattr(args, "client_host", None) or args.prefill_host
    exitcode = remote_text(client_host, remote / "job.exitcode").strip()
    if exitcode != "0":
        raise ValueError(f"Workload did not succeed: exit={exitcode}")
    workload = json.loads(remote_text(client_host, remote / "workload.json"))
    if workload.get("protocol") == "time":
        return collect_time(args, owner, output, target, remote, workload)
    if (workload.get("C") != args.concurrency or workload.get("K") != 5
        or workload.get("successful") != 5 * args.concurrency
        or workload.get("completed") != 5 * args.concurrency):
        raise ValueError("Workload identity or success count mismatch")
    stage = Path(tempfile.mkdtemp(prefix=f".C{args.concurrency}-", dir=output))
    manifest = []
    try:
        for role, host in (("prefill", args.prefill_host), ("decode", args.decode_host)):
            records = json.loads(remote_text(host, remote / f"native-validation-{role}.json"))
            identities = {(r.get("phase"), r.get("tp_rank")) for r in records}
            expected = {(phase, rank) for phase in ("initial", "after-prerun")
                        for rank in range(args.tp_size)}
            if len(records) != len(expected) or identities != expected:
                raise ValueError(f"Missing or duplicate phase/rank records for {role}")
            for record in records:
                count = 4 if role == "prefill" else 128
                if (not record.get("complete") or record.get("captured_steps") != count
                    or record.get("role") != role):
                    raise ValueError(f"Incomplete native window: {record}")
                name = record["trace"]
                if PurePosixPath(name).name != name or name in (".", ".."):
                    raise ValueError("Unsafe trace name in validation record")
                phase, rank = record["phase"], record["tp_rank"]
                source_subdir = record.get('source_subdir', f'{phase}/{role}')
                if source_subdir not in (phase, f'{phase}/{role}'):
                    raise ValueError('Unsafe source subdirectory in validation record')
                source = remote / source_subdir / name
                folder = stage / phase / role
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / f"TP-{rank}.trace.json.gz"
                fetch(host, source, destination)
                with destination.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if destination.stat().st_size != record["bytes"] or digest != record["sha256"]:
                    raise ValueError(f"Size/hash mismatch: {destination}")
                summary = {**record, "source_trace": name, "trace": destination.name}
                (folder / f"window-{role}-TP-{rank}.json").write_text(
                    json.dumps(summary, indent=2)+"\n", encoding="utf-8")
                manifest.append({**summary, "source_host":host, "source_path":str(source),
                                 "local_path":str(destination.relative_to(stage))})
                print(f"Verified {phase}/{role}/TP{rank}: {record['bytes']} bytes", flush=True)
        (stage / "workload.json").write_text(json.dumps(workload, indent=2)+"\n", encoding="utf-8")
        text = (f"# Native Profiler C{args.concurrency}\n\nRun: `{args.run}`. "
                "K=5; warmup=2; initial and after-4C; P4/D128; no native aggregation.\n\n"
                "All source windows and local SHA-256/size checks passed. "
                "after-prerun is not a guarantee of steady state. "
                "See workload.json for actual resolved control bodies and timing.\n\n"
                "| File | Bytes | SHA-256 |\n|---|---:|---|\n")
        owner_label = owner.relative_to(project).as_posix()
        text = text.replace("\n\nRun:", f"\n\nResult owner: `{owner_label}`.\n\nRun:", 1)
        text += "\n".join(f"| {r['local_path']} | {r['bytes']} | {r['sha256']} |" for r in manifest)
        text += "\n\n## Source mapping\n\n```json\n" + json.dumps(manifest, indent=2) + "\n```\n"
        (stage / "MANIFEST.md").write_text(text, encoding="utf-8")
        backup = None
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".C{args.concurrency}-previous-", dir=output))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            if backup is not None:
                os.replace(backup, target)
            raise
        if backup is not None:
            if backup.resolve().parent != output.resolve() or not backup.name.startswith(f".C{args.concurrency}-previous-"):
                raise ValueError("Refusing cleanup outside verified result directory")
            shutil.rmtree(backup)
        print(f"Delivered {len(manifest)} traces, {sum(r['bytes'] for r in manifest)} bytes: {target}", flush=True)
        return target
    except Exception:
        print(f"Partial staging preserved for diagnosis: {stage}", flush=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--result-owner", help="Existing experiment-relative tuning/<study>/baseline or tuning/<study>/candidates/<id>; ordinary captures omit this")
    parser.add_argument("--run", required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--remote-project", required=True)
    parser.add_argument("--prefill-host")
    parser.add_argument("--decode-host")
    parser.add_argument("--single-host", help="Both stages originate from this single-service host")
    parser.add_argument("--tp-size", type=int, required=True)
    parser.add_argument("--client-host", help="Actual workload source host; defaults to prefill-host only for compatibility")
    parser.add_argument("--prefill-tp-size", type=int)
    parser.add_argument("--decode-tp-size", type=int)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.single_host:
        if args.prefill_host or args.decode_host:
            parser.error('Use --single-host or the two PD hosts, not both')
        args.prefill_host = args.decode_host = args.single_host
    elif not args.prefill_host or not args.decode_host:
        parser.error('Specify --single-host or both PD hosts')
    if args.concurrency < 1 or args.tp_size < 1 or any(v is not None and v < 1 for v in (args.prefill_tp_size, args.decode_tp_size)):
        parser.error("Concurrency and TP size must be positive")
    collect(args)
