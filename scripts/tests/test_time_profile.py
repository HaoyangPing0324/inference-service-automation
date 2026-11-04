"""Behavioral capture/control/recovery tests; no GPU, SGLang, Docker or SSH."""
import asyncio
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "scripts/templates/shared/client"
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

runtime = module("time_capture", SHARED / "time_profile.py")
validation = module("time_validation", SHARED / "validate_time_window.py")
collector = module("time_collector", ROOT / "scripts/collect_profiler_results.py")


class TimeProfileTests(unittest.TestCase):
    def args(self, directory, pd=False, mode="torch", **overrides):
        data = dict(concurrency=3, output_dir=Path(directory), base_url="http://router",
                    prefill_url=["http://p"] if pd else [], decode_url=["http://d"] if pd else [],
                    prefix="test", mode=mode, prerun_seconds=.01, capture_seconds=.025,
                    max_requests=1000, request_timeout=2, control_timeout=2, ready_timeout=2,
                    isl=128, osl=32, seed=1, dataset_path="local", model_path="model")
        return SimpleNamespace(**(data | overrides))

    def exercise(self, args, failure=None):
        lock = threading.Lock()
        state = {"active": 0, "maximum": 0, "generated": 0}
        calls = []
        def transport(url, body, timeout):
            with lock:
                calls.append((url, body))
            if failure and failure(url, body):
                raise RuntimeError("injected failure")
            if url.endswith("/generate"):
                with lock:
                    state["active"] += 1
                    state["maximum"] = max(state["maximum"], state["active"])
                    state["generated"] += 1
                time.sleep(.002)
                with lock:
                    state["active"] -= 1
                return json.dumps({"meta_info": {"completion_tokens": 32}})
            time.sleep(.001 if url.startswith("http://p") else .002)
            return '{"success": true}'
        healthy = {"workers": []}
        ready = lambda *args: True
        run = runtime.TimeWindowRun(args, [SimpleNamespace(prompt="test")] * 4,
                                    transport, lambda url: healthy, ready)
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(run.run())
        return run, calls, state

    def test_single_and_pd_both_tools_continuous_load_and_common_interval(self):
        for pd, c in ((False, 1), (False, 16), (True, 1), (True, 16)):
            for mode in ("torch", "nsys"):
                with self.subTest(pd=pd, mode=mode, c=c), tempfile.TemporaryDirectory() as tmp:
                    args = self.args(tmp, pd, mode, concurrency=c)
                    run, calls, state = self.exercise(args)
                    data = json.loads((Path(tmp) / "workload.json").read_text())
                    self.assertEqual(validation.validate_workload(data), {"prefill", "decode"} if pd else {"single"})
                    self.assertGreaterEqual(data["control_common_interval_seconds"], args.capture_seconds)
                    self.assertEqual(state["generated"], run.issued + 2)
                    self.assertEqual(run.issued, run.successful)
                    self.assertLessEqual(state["maximum"], args.concurrency)
                    starts = [(u, b) for u, b in calls if u.endswith("/start_profile")]
                    self.assertEqual(len(starts), 2 if pd else 1)
                    self.assertTrue(all("num_steps" not in b and b["profile_by_stage"] is False for _, b in starts))
                    self.assertTrue(all(b["activities"] == (["CPU", "GPU"] if mode == "torch" else ["CUDA_PROFILER"]) for _, b in starts))
                    if pd:
                        self.assertFalse(any(u.startswith("http://router/") for u, _ in starts))
                    self.assertGreater(next(e["issued"] for e in run.events if e["event"] == "capture-started"), 0)
                    self.assertGreaterEqual(next(e["completed"] for e in run.events if e["event"] == "capture-started"), 4*args.concurrency)
                    stopped = next(e for e in run.events if e["event"] == "capture-stopped")
                    after = next(e for e in run.events if e["event"] == "postrun-complete")
                    self.assertGreaterEqual(after["completed"], stopped["completed"] + args.concurrency)
                    self.assertEqual(state["active"], 0)

    def test_real_cli_dispatch_defaults_to_one_middle_window_for_both_topologies(self):
        for kind, pd in (("inference-project", False), ("inference-project-pd", True)):
            for mode in ("torch", "nsys"):
                with self.subTest(kind=kind, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    entry = ROOT / "scripts/templates" / kind / "client/run_time_profile.py"
                    cli = module("cli_middle", entry)
                    argv = [str(entry), "--mode", mode, "--concurrency", "1", "--base-url", "http://router",
                            "--model-path", "local", "--model", "model", "--dataset-path", "local.json",
                            "--prefix", "test", "--isl", "128", "--osl", "32", "--seed", "1",
                            "--output-dir", tmp, "--capture-seconds", ".01"]
                    if pd:
                        argv += ["--prefill-url", "http://p", "--decode-url", "http://d"]
                    calls = []
                    def transport(url, body, timeout):
                        calls.append((url, body))
                        time.sleep(.001)
                        return '{"meta_info": {}}' if url.endswith("/generate") else '{"success":true}'
                    healthy = {"workers": [{"url": "http://p", "worker_type": "prefill", "is_healthy": True},
                                            {"url": "http://d", "worker_type": "decode", "is_healthy": True}]}
                    with patch.object(sys, "argv", argv), patch.object(sys, "path", [str(entry.parent)] + sys.path), \
                         patch.object(cli, "post", transport), patch.object(cli, "get_workers", lambda u: healthy), \
                         patch.object(cli, "load_requests", lambda a: [SimpleNamespace(prompt="test")] * 5), \
                         contextlib.redirect_stdout(io.StringIO()):
                        cli.main()
                    data = json.loads((Path(tmp) / "workload.json").read_text())
                    validation.validate_workload(data)
                    self.assertFalse((Path(tmp) / "initial").exists())
                    self.assertFalse((Path(tmp) / "after-prerun").exists())
                    self.assertEqual(len([u for u, b in calls if u.endswith("/start_profile")]), 2 if pd else 1)

    def test_budget_exhaustion_is_failure_not_truncated_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                self.exercise(self.args(tmp, max_requests=30, capture_seconds=1))
            data = json.loads((Path(tmp) / "workload.json").read_text())
            self.assertEqual(data["status"], "incomplete")
            with self.assertRaises(ValueError):
                validation.validate_workload(data)

    def test_partial_start_failure_stops_every_attempted_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.exercise(self.args(tmp, pd=True), lambda u, b: u == "http://d/start_profile")
            data = json.loads((Path(tmp) / "workload.json").read_text())
            self.assertEqual({r["role"] for r in data["controls"] if r["action"] == "stop"}, {"prefill", "decode"})
            self.assertNotEqual(data["status"], "captured-unvalidated")

    def test_stop_failure_cannot_be_accepted_as_native_auto_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.exercise(self.args(tmp), lambda u, b: u.endswith("stop_profile"))
            data = json.loads((Path(tmp) / "workload.json").read_text())
            with self.assertRaises(ValueError):
                validation.validate_workload(data)
            self.assertTrue(any(e["event"] == "cleanup-unconfirmed" for e in data["events"]))

    def test_invalid_time_or_budget_rejected_without_transport(self):
        for values in ({"capture_seconds": 0}, {"capture_seconds": float("nan")},
                       {"prerun_seconds": -1}, {"max_requests": 1}):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    runtime.TimeWindowRun(self.args(tmp, **values), [None], lambda *a: self.fail("request sent"))

    def trace(self, path, stages=("EXTEND", "DECODE"), gpu=True):
        rows = [{"ph": "X", "cat": "gpu_user_annotation", "pid": 1, "tid": 1,
                 "name": f"step[{s} bs=2]"} for s in stages]
        rows += [dict(e, tid=2) for e in rows]  # Duplicate GPU track, not extra steps.
        if gpu:
            rows.append({"ph": "X", "cat": "kernel", "name": "compute"})
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump({"traceEvents": rows}, stream)

    def test_mixed_trace_coverage_not_fixed_counts_and_preserves_both_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            native_path = str(ROOT / "scripts/templates/inference-project/client")
            with patch.object(sys, "path", [native_path] + sys.path):
                trace = Path(tmp) / "mixed.trace.json.gz"
                self.trace(trace)
                summary = validation.summarize(trace, "single", 0)
                self.assertTrue(summary["complete"])
                self.assertEqual(summary["stages"]["prefill"]["steps"], 1)
                self.assertEqual(summary["stages"]["decode"]["steps"], 1)
                self.trace(trace, ("DECODE",))
                self.assertFalse(validation.summarize(trace, "single", 0)["complete"])
                self.assertTrue(validation.summarize(trace, "decode", 0)["complete"])
                self.trace(trace, gpu=False)
                self.assertFalse(validation.summarize(trace, "single", 0)["complete"])

    def test_mixed_collection_uses_client_host_and_checks_local_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            project = Path(tmp) / "project"
            project.mkdir()
            args = self.args(source)
            self.exercise(args)
            folder = source / "capture/single"
            folder.mkdir(parents=True)
            trace = folder / "test-TP-0.trace.json.gz"
            self.trace(trace)
            workload = json.loads((source / "workload.json").read_text())
            native_path = str(ROOT / "scripts/templates/inference-project/client")
            with patch.object(sys, "path", [native_path] + sys.path):
                validation.validate(source, "single", 1, workload)
            collection = SimpleNamespace(project=project, concurrency=args.concurrency, replace=False,
                remote_project="/runtime/project", run="run", prefill_host="server", decode_host="server",
                client_host="client", tp_size=1)
            def remote(host, path):
                if path.name == "job.exitcode":
                    self.assertEqual(host, "client")
                    return "0"
                if path.name == "workload.json":
                    self.assertEqual(host, "client")
                    return json.dumps(workload)
                self.assertEqual(host, "server")
                return (source / path.name).read_text()
            def fetch(host, remote, dest):
                dest.write_bytes(trace.read_bytes())
            with patch.object(collector, "remote_text", remote), patch.object(collector, "fetch", fetch):
                result = collector.collect(collection)
            self.assertTrue((result / "capture/single/TP-0.trace.json.gz").is_file())
            self.assertFalse((result / "capture/prefill").exists())


if __name__ == "__main__":
    unittest.main()
