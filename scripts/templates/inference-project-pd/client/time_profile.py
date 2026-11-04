#!/usr/bin/env python3
"""Bounded wall-time SGLang capture under a continuously replenished load.

No stage hook, stage limit, router profiling, or benchmark implementation is used.
Control timestamps are client observations, not synchronized GPU timestamps.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time


class TimeWindowRun:
    def __init__(self, args, rows, transport, get_workers=None, workers_ready=None):
        self.args, self.rows, self.transport = args, rows, transport
        self.prerun_multiplier = getattr(args, "prerun_completed_multiplier", 4)
        self.postrun_multiplier = getattr(args, "postrun_completed_multiplier", 1)
        self.get_workers, self.workers_ready = get_workers, workers_ready
        self.endpoints = ([("prefill", u) for u in args.prefill_url]
                          + [("decode", u) for u in args.decode_url]
                          if args.prefill_url else [("single", args.base_url)])
        if not rows:
            raise ValueError("Empty profiling request pool")
        if (args.output_dir / "workload.json").exists():
            raise ValueError("Run already contains workload.json; select a new isolated run")
        for name in ("capture_seconds", "request_timeout", "control_timeout"):
            value = getattr(args, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(args.prerun_seconds) or args.prerun_seconds < 0:
            raise ValueError("prerun_seconds must be finite and nonnegative")
        if (args.concurrency < 1 or self.prerun_multiplier < 1 or self.postrun_multiplier < 1
            or args.max_requests < (self.prerun_multiplier + self.postrun_multiplier + 1) * args.concurrency):
            raise ValueError("max_requests must cover prerun, capture and postrun at the selected concurrency")
        self.events, self.outputs = [], []
        self.issued = self.completed = self.successful = 0
        self.accepting = False
        self.failure = asyncio.Event()
        self.progress = asyncio.Event()
        self.failure_reason = None
        self.attempted = set()
        self.control_records = []
        self.status = "incomplete"
        self.load_started = None
        self.capture_started = self.capture_stopped = None

    def event(self, kind, **values):
        record = {"event": kind, "time": time.time(), "monotonic": time.monotonic(), **values}
        self.events.append(record)
        print(json.dumps(record), flush=True)

    def fail(self, reason):
        if not self.failure.is_set():
            self.failure_reason = str(reason)
            self.event("failure", reason=str(reason))
            self.failure.set()
            self.progress.set()
        self.accepting = False

    async def request(self, row):
        started, mono = time.time(), time.monotonic()
        body = {"text": row.prompt, "stream": False, "sampling_params": {
            "max_new_tokens": self.args.osl, "temperature": 0, "ignore_eos": True}}
        raw = await asyncio.to_thread(self.transport, self.args.base_url.rstrip("/") + "/generate",
                                     body, self.args.request_timeout)
        data = json.loads(raw)
        if not isinstance(data, dict) or "error" in data or "meta_info" not in data:
            raise RuntimeError("Invalid generation response")
        meta = data["meta_info"]
        if (meta.get("finish_reason") or {}).get("type") in ("abort", "error"):
            raise RuntimeError(f"Generation failed: {meta}")
        return {"started": started, "finished": time.time(),
                "elapsed_seconds": time.monotonic() - mono, "meta_info": meta}

    async def worker(self):
        while self.accepting:
            if self.issued >= self.args.max_requests:
                self.fail("Request safety budget exhausted before capture finished")
                return
            index = self.issued
            self.issued += 1
            try:
                result = await self.request(self.rows[index % len(self.rows)])
            except Exception as exc:
                self.completed += 1
                self.outputs.append({"index": index, "error": str(exc)})
                self.fail(exc)
                return
            self.completed += 1
            self.successful += 1
            self.outputs.append({"index": index, "pool_index": index % len(self.rows), **result})
            self.progress.set()

    async def wait_completed(self, target):
        while self.completed < target:
            if self.failure.is_set():
                raise RuntimeError(self.failure_reason)
            self.progress.clear()
            await self.progress.wait()
        if self.failure.is_set():
            raise RuntimeError(self.failure_reason)

    async def wait_loaded(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            if self.failure.is_set():
                raise RuntimeError(self.failure_reason)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self.failure.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                # Event loop timers may wake slightly early on some caller OSes.
                continue
            raise RuntimeError(self.failure_reason)

    async def control(self, action, endpoints=None):
        async def one(role, url):
            key = (role, url)
            if action == "start":
                # A timeout may mean the server started. Attempt cleanup even then.
                self.attempted.add(key)
            body = {} if action == "stop" else {
                "output_dir": str(self.args.output_dir / "capture" / role),
                "activities": ["CPU", "GPU"] if self.args.mode == "torch" else ["CUDA_PROFILER"],
                "profile_by_stage": False,
                "profile_prefix": self.args.prefix + "-capture",
                "detailed_annotations": True,
            }
            endpoint = url.rstrip("/") + f"/{action}_profile"
            record = {"action": action, "role": role, "endpoint": endpoint, "body": body,
                      "sent": time.time(), "sent_monotonic": time.monotonic(),
                      "completed_at_send": self.completed, "issued_at_send": self.issued}
            self.control_records.append(record)
            try:
                response = await asyncio.to_thread(self.transport, endpoint, body, self.args.control_timeout)
                # Some versions return HTTP 200 with an explicit unsuccessful result.
                try:
                    parsed = json.loads(response)
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, dict) and (parsed.get("success") is False or "error" in parsed):
                    raise RuntimeError(f"Profile control rejected: {response}")
                record.update(response=response, success=True)
                if action == "stop":
                    self.attempted.discard(key)
            except Exception as exc:
                record.update(error=str(exc), success=False)
                raise
            finally:
                record.update(received=time.time(), received_monotonic=time.monotonic())
                self.event("profile-control", **record)
        results = await asyncio.gather(*(one(*entry) for entry in (endpoints or self.endpoints)),
                                       return_exceptions=True)
        errors = [str(r) for r in results if isinstance(r, BaseException)]
        if errors:
            raise RuntimeError("; ".join(errors))

    def save(self):
        starts = [r for r in self.control_records if r["action"] == "start" and r.get("success")]
        stops = [r for r in self.control_records if r["action"] == "stop" and r.get("success")]
        # This is a conservative interval between successful start acknowledgements
        # and first stop dispatch. It is not GPU/rank clock alignment evidence.
        overlap = (min(r["sent_monotonic"] for r in stops)
                   - max(r["received_monotonic"] for r in starts)) if starts and stops else None
        payload = {"protocol": "time", "mode": self.args.mode, "status": self.status,
                   "C": self.args.concurrency, "warmup_requests": 2,
                   "prerun_seconds": self.args.prerun_seconds,
                   "prerun_completed_multiplier": self.prerun_multiplier,
                   "postrun_completed_multiplier": self.postrun_multiplier,
                   "capture_seconds": self.args.capture_seconds,
                   "max_requests": self.args.max_requests, "request_pool_size": len(self.rows),
                   "pool_reuse": "cyclic; prefix cache must be disabled for comparable load",
                   "ISL": self.args.isl, "OSL": self.args.osl, "seed": self.args.seed,
                   "dataset_path": self.args.dataset_path, "tokenizer": self.args.model_path,
                   "issued": self.issued, "completed": self.completed, "successful": self.successful,
                   "control_common_interval_seconds": overlap,
                   "clock_basis": "client monotonic control brackets; not aligned GPU clocks",
                   "controls": self.control_records, "events": self.events, "requests": self.outputs,
                   "failure": self.failure_reason}
        self.args.output_dir.mkdir(parents=True, exist_ok=True)
        (self.args.output_dir / "workload.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    async def run(self):
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=self.args.concurrency + len(self.endpoints) + 2))
        tasks = []
        try:
            if self.args.prefill_url:
                deadline = time.monotonic() + self.args.ready_timeout
                while True:
                    data = await asyncio.to_thread(self.get_workers, self.args.base_url)
                    if self.workers_ready(data, self.args.prefill_url, self.args.decode_url):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Router did not mark configured PD workers healthy")
                    await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
            sem = asyncio.Semaphore(self.args.concurrency)
            async def warmup():
                async with sem:
                    await self.request(self.rows[0])
            await asyncio.gather(warmup(), warmup())
            self.event("warmup-complete", requests=2)
            self.accepting = True
            self.load_started = time.monotonic()
            tasks = [asyncio.create_task(self.worker()) for _ in range(self.args.concurrency)]
            await asyncio.sleep(0)  # Dispatch the initial workers before the prerun timer.
            self.event("load-started", issued=self.issued)
            await self.wait_completed(self.prerun_multiplier * self.args.concurrency)
            await self.wait_loaded(max(0, self.args.prerun_seconds - (time.monotonic() - self.load_started)))
            self.event("prerun-complete", completed=self.completed, issued=self.issued,
                       target_completed=self.prerun_multiplier * self.args.concurrency)
            await self.control("start")
            self.capture_started = time.monotonic()
            self.event("capture-started", completed=self.completed, issued=self.issued)
            await self.wait_loaded(self.args.capture_seconds)
            self.capture_stopped = time.monotonic()
            await self.control("stop")
            # Keep the window away from the load tail: replenish through export,
            # then complete at least another multiplier*C requests after stop ACKs.
            postrun_target = self.completed + self.postrun_multiplier * self.args.concurrency
            self.event("capture-stopped", completed=self.completed, postrun_target=postrun_target)
            await self.wait_completed(postrun_target)
            self.accepting = False
            self.event("postrun-complete", completed=self.completed, target_completed=postrun_target)
            await asyncio.gather(*tasks)
            if self.failure.is_set():
                raise RuntimeError(self.failure_reason)
            self.status = "captured-unvalidated"
            self.event("capture-complete", successful=self.successful)
        except BaseException as exc:
            self.fail(exc)
            raise
        finally:
            self.accepting = False
            if self.attempted:
                try:
                    await self.control("stop", sorted(self.attempted))
                except Exception as exc:
                    self.event("cleanup-unconfirmed", error=str(exc))
            # Do not abandon blocking HTTP requests; each has its own timeout.
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.save()
