#!/usr/bin/env python3
"""SGLang-only profiler: one middle time window; explicit legacy steps mode.

Does not modify or import benchmark.serving. Run inside the service image.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import random
import time
import urllib.request
import urllib.error
from pathlib import Path

K, PRERUN_MULTIPLIER, WARMUP_REQUESTS = 5, 4, 2


def post(url, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode()


def get_workers(base_url):
    with urllib.request.urlopen(base_url.rstrip('/') + '/workers', timeout=10) as response:
        return json.load(response)


def pd_workers_ready(data, prefill_urls, decode_urls):
    workers = data.get('workers', [])
    return all(any(w.get('url', '').rstrip('/') == url.rstrip('/')
                   and w.get('worker_type') == role and w.get('is_healthy') is True
                   for w in workers)
               for role, urls in (('prefill', prefill_urls), ('decode', decode_urls))
               for url in urls)


def load_requests(args):
    # Fail before the framework loader, which otherwise downloads ShareGPT.
    dataset = Path(args.dataset_path)
    with dataset.open(encoding="utf-8") as stream:
        entries = json.load(stream)
    if not isinstance(entries, list) or not any(
        len(row.get("conversations", row.get("conversation", []))) >= 2
        for row in entries if isinstance(row, dict)
    ):
        raise ValueError("Local ShareGPT has no usable conversations")
    del entries
    model = Path(args.model_path)
    if not model.is_dir():
        raise ValueError("Tokenizer must be the mounted local model directory")
    import numpy as np
    from transformers import AutoTokenizer
    from sglang.benchmark.datasets.random import sample_random_requests
    random.seed(args.seed)
    np.random.seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(
        str(model), trust_remote_code=True, local_files_only=True)
    return sample_random_requests(
        input_len=args.isl, output_len=args.osl,
        num_prompts=K * args.concurrency, range_ratio=1.0,
        tokenizer=tokenizer, dataset_path=str(dataset),
        random_sample=True, return_text=True)


class WindowRun:
    def __init__(self, args, rows, transport=post):
        self.args, self.rows, self.transport = args, rows, transport
        self.total, self.threshold = K * args.concurrency, PRERUN_MULTIPLIER * args.concurrency
        self.completed = self.successful = self.next_index = 0
        self.gate = asyncio.Event()
        self.gate.set()
        self.transition_task = None
        self.phase = "initial"
        self.events, self.outputs = [], []
        self.endpoints = (
            [("prefill", u) for u in args.prefill_url]
            + [("decode", u) for u in args.decode_url]
            if args.prefill_url or args.decode_url else [("single", args.base_url)])
        if not args.prefill_url and args.prefill_steps != args.decode_steps and not getattr(args, 'single_stage_adapter', False):
            raise ValueError("Single-service native API has one num_steps. P4/D128 requires an explicitly approved adapter; no hook is enabled automatically.")

    def event(self, kind, **values):
        item = {"event": kind, "time": time.time(), **values}
        self.events.append(item)
        print(json.dumps(item), flush=True)

    def save(self):
        self.args.output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "C": self.args.concurrency, "K": K, "N": self.total,
            "warmup_requests": WARMUP_REQUESTS,
            "after_prerun_target_completed": self.threshold,
            "prefill_steps": self.args.prefill_steps, "decode_steps": self.args.decode_steps,
            "ISL": self.args.isl, "OSL": self.args.osl,
            "dataset_path": self.args.dataset_path, "tokenizer": self.args.model_path,
            "seed": self.args.seed, "completed": self.completed,
            "successful": self.successful, "events": self.events, "requests": self.outputs}
        result['single_stage_adapter'] = getattr(self.args, 'single_stage_adapter', False)
        (self.args.output_dir / "workload.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")

    async def request(self, row):
        body = {"text": row.prompt, "stream": False, "sampling_params": {
            "max_new_tokens": self.args.osl, "temperature": 0, "ignore_eos": True}}
        started = time.time()
        raw = await asyncio.to_thread(self.transport,
            self.args.base_url.rstrip("/") + "/generate", body, self.args.request_timeout)
        data = json.loads(raw)
        if not isinstance(data, dict) or "error" in data or "meta_info" not in data:
            raise RuntimeError(f"Invalid generation response: {str(data)[:300]}")
        meta = data["meta_info"]
        if (meta.get("finish_reason") or {}).get("type") in ("abort", "error"):
            raise RuntimeError(f"Generation failed: {meta}")
        return {"started": started, "finished": time.time(), "meta_info": meta}

    async def control(self, phase, action):
        async def one(role, url):
            directory = self.args.output_dir / phase
            if role != "single":
                directory /= role
            body = {} if action == "stop" else {
                "output_dir": str(directory),
                "activities": ["CPU", "GPU"] if self.args.mode == "torch" else ["CUDA_PROFILER"],
                "profile_by_stage": True,
                "num_steps": self.args.decode_steps if role == "decode" else self.args.prefill_steps,
                "profile_prefix": f"{self.args.prefix}-{phase}",
                "detailed_annotations": True}
            endpoint = url.rstrip("/") + f"/{action}_profile"
            try:
                response = await asyncio.to_thread(
                    self.transport, endpoint, body, self.args.control_timeout)
            except urllib.error.HTTPError as exc:
                if action != "stop" or exc.code != 500:
                    raise
                # Native auto-stop is not idempotent. A generic HTTP 500 does
                # not prove completion: leave it explicitly unconfirmed until
                # rank traces/logs have been checked on their source hosts.
                self.event("profile-stop-unconfirmed", phase=phase, role=role,
                    endpoint=endpoint, http_status=exc.code,
                    response=exc.read().decode(errors="replace"),
                    requires_native_validation=True)
                return
            self.event("profile-control", phase=phase, role=role, endpoint=endpoint,
                body=body, response=response.strip(), completed=self.completed,
                issued=self.next_index)
        await asyncio.gather(*(one(role, url) for role, url in self.endpoints))

    async def transition(self):
        try:
            # A synchronization barrier, not a fresh workload. Export can delay
            # admission: record actual completions, never claim steady state.
            await self.control("initial", "stop")
            await self.control("after-prerun", "start")
            self.phase = "after-prerun"
            self.event("after-prerun-started", target=self.threshold,
                completed=self.completed, issued=self.next_index)
        finally:
            self.gate.set()

    async def worker(self):
        while True:
            await self.gate.wait()
            if self.transition_task and self.transition_task.done():
                self.transition_task.result()
            if self.next_index >= self.total:
                return
            index = self.next_index
            self.next_index += 1
            result = await self.request(self.rows[index])
            self.completed += 1
            self.successful += 1
            self.outputs.append({"index": index, **result})
            self.event("request-complete", index=index, completed=self.completed, total=self.total)
            if self.completed == self.threshold:
                self.gate.clear()
                self.transition_task = asyncio.create_task(self.transition())

    async def run(self):
        # Keep control calls independent of a full set of blocking HTTP workers.
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=self.args.concurrency + len(self.endpoints) + 2))
        sem = asyncio.Semaphore(self.args.concurrency)
        async def warmup():
            async with sem:
                await self.request(self.rows[0])
        try:
            if self.args.prefill_url:
                deadline = time.monotonic() + getattr(self.args, 'ready_timeout', 1800)
                while True:
                    try:
                        data = await asyncio.to_thread(get_workers, self.args.base_url)
                        if pd_workers_ready(data, self.args.prefill_url, self.args.decode_url):
                            break
                    except (OSError, ValueError) as exc:
                        self.event('router-readiness-wait', error=str(exc))
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Router did not mark all configured PD workers healthy')
                    await asyncio.sleep(10)
                self.event('router-workers-ready')
            await asyncio.gather(*(warmup() for _ in range(WARMUP_REQUESTS)))
            self.event("warmup-complete", requests=WARMUP_REQUESTS)
            await self.control("initial", "start")
            tasks = [asyncio.create_task(self.worker()) for _ in range(self.args.concurrency)]
            try:
                await asyncio.gather(*tasks)
                if self.transition_task:
                    await self.transition_task
                if self.phase != "after-prerun":
                    raise RuntimeError("Second window was not armed")
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if self.transition_task and not self.transition_task.done():
                    await self.transition_task
                await self.control(self.phase, "stop")
            self.event("workload-complete", successful=self.successful)
        finally:
            self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("torch", "nsys"), required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    for name in ("base-url", "model-path", "model", "dataset-path", "prefix"):
        parser.add_argument("--" + name, required=True)
    for name in ("isl", "osl", "seed"):
        parser.add_argument("--" + name, type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefill-url", action="append", default=[])
    parser.add_argument("--decode-url", action="append", default=[])
    parser.add_argument("--prefill-steps", type=int, default=4)
    parser.add_argument("--decode-steps", type=int, default=128)
    parser.add_argument("--request-timeout", type=int, default=1800)
    parser.add_argument("--control-timeout", type=int, default=1800)
    parser.add_argument("--ready-timeout", type=int, default=1800)
    parser.add_argument("--single-stage-adapter", action="store_true",
                        help="Use only when the single-service stage adapter has explicit approval")
    parser.add_argument("--protocol", choices=("time", "steps"), default="time")
    parser.add_argument("--prerun-seconds", type=float, default=0)
    parser.add_argument("--prerun-completed-multiplier", type=int, default=4)
    parser.add_argument("--postrun-completed-multiplier", type=int, default=1)
    parser.add_argument("--capture-seconds", type=float, default=15)
    parser.add_argument("--max-requests", type=int, default=100000)
    args = parser.parse_args()
    if min(args.concurrency, args.isl, args.osl, args.prefill_steps, args.decode_steps) < 1:
        parser.error("Concurrency, lengths and steps must be positive")
    if bool(args.prefill_url) != bool(args.decode_url):
        parser.error("PD requires both prefill and decode endpoints")
    # Validate topology before loading data or submitting any requests.
    if args.protocol == "time":
        if args.single_stage_adapter:
            parser.error("Time capture uses the native mixed profiler, without a stage adapter")
        from time_profile import TimeWindowRun
        # Validate time/budget fields before loading datasets or making requests.
        TimeWindowRun(args, [None], post, get_workers, pd_workers_ready)
        asyncio.run(TimeWindowRun(args, load_requests(args), post, get_workers, pd_workers_ready).run())
        return
    if not args.prefill_url and args.prefill_steps != args.decode_steps and not args.single_stage_adapter:
        parser.error("Native single-service API cannot set P4/D128 separately; ask before enabling an adapter")
    asyncio.run(WindowRun(args, load_requests(args)).run())


if __name__ == "__main__":
    main()
