# h20_glm-v53-flash_sglang_single

## 1. 启动服务

### 准备

single-node宿主机：

```bash
# Linux、Docker及NVIDIA容器运行时已就绪
# 模型与tokenizer放入以下MODEL_DIR
MODEL_DIR=/srv/models/GLM/GLM-5.3-Flash
DATASET=/srv/datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json
test -r "$MODEL_DIR/config.json"
test -r "$MODEL_DIR/tokenizer_config.json"
test -r "$DATASET"
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/server /srv/inference/h20_glm-v53-flash_sglang_single/client
docker pull lmsysorg/sglang:v0.5.21
```

### 容器与模型服务

```bash
docker pull lmsysorg/sglang:v0.5.21
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/{server/profiling_hooks,client}
docker run -d --name h20_glm-v53-flash_sglang_single-server \
  --runtime nvidia-container-runtime \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -p 30080:30000 --ipc=host \
  -v /srv/models:/models:ro \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/server:/server \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/client:/client \
  -w /server lmsysorg/sglang:v0.5.21 sleep infinity
docker run -d --name h20_glm-v53-flash_sglang_single-client \
  --network container:h20_glm-v53-flash_sglang_single-server \
  -v /srv/models:/models:ro -v /srv/datasets:/datasets:ro \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/server:/server \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/client:/client \
  -w /client lmsysorg/sglang:v0.5.21 sleep infinity

docker exec -d h20_glm-v53-flash_sglang_single-server sglang serve \
  --model-path /models/GLM/GLM-5.3-Flash --served-model-name glm-53-flash \
  --tp-size 8 --ep-size 8 --mem-fraction-static 0.75 \
  --dsa-prefill-backend tilelang --dsa-decode-backend tilelang \
  --kv-cache-dtype bfloat16 --moe-runner-backend deep_gemm \
  --host 0.0.0.0 --port 30000 --reasoning-parser auto --tool-call-parser auto \
  --disable-radix-cache
```

### 就绪与真实对话

宿主机执行：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/client
```

保存为 `/srv/inference/h20_glm-v53-flash_sglang_single/client/check_ready.py`：

```python
import time
import urllib.request

deadline = time.monotonic() + 900
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:30000/health", timeout=5):
            break
    except OSError:
        if time.monotonic() >= deadline:
            raise TimeoutError("Service not ready")
        time.sleep(10)
print("health ready; chat is checked separately")
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/client
```

保存为 `/srv/inference/h20_glm-v53-flash_sglang_single/client/chat_test.py`：

```python
"""One real chat request; fail on HTTP/model/schema/empty-content errors."""
import json
import sys
import urllib.request

port, model = sys.argv[1:]
payload = {"model": model, "messages": [{"role": "user", "content": "Hello"}]}
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(request, timeout=300) as response:
    result = json.load(response)
if result.get("model") != model:
    raise RuntimeError(f"Unexpected model: {result.get('model')!r}")
choices = result.get("choices")
if not isinstance(choices, list) or not choices:
    raise RuntimeError("Response has no choices")
message = choices[0].get("message")
if not isinstance(message, dict):
    raise RuntimeError("Response has no assistant message")
content = message.get("content")
if not isinstance(content, str) or not content.strip():
    raise RuntimeError("Response has no final assistant content")
print(json.dumps({"request": payload, "response": result},
                 ensure_ascii=False, indent=2))
```

```bash
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/check_ready.py
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/chat_test.py 30000 glm-53-flash
```

结果：未测。

## 2. Baseline压测

```bash
set -euo pipefail
MODE=full
case "$MODE" in
  full) CONCURRENCIES=(1 2 4 8 16 32) ;;
  tuning) CONCURRENCIES=(1 8 32) ;;
  *) exit 2 ;;
esac
OUT=/client/results/glm-v53-flash-baseline
docker exec h20_glm-v53-flash_sglang_single-client mkdir -p "$OUT"
for C in "${CONCURRENCIES[@]}"; do
  N=$((C * 5))
  SEED=$((20260923 + 16384 + C))
  docker exec h20_glm-v53-flash_sglang_single-client \
    python3 -m sglang.benchmark.serving \
    --backend sglang --host 127.0.0.1 --port 30000 \
    --model /models/GLM/GLM-5.3-Flash --served-model-name glm-53-flash \
    --tokenizer /models/GLM/GLM-5.3-Flash \
    --dataset-name random --random-range-ratio 1.0 \
    --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
    --random-input-len 16384 --random-output-len 2048 \
    --warmup-requests 2 --num-prompts "$N" --max-concurrency "$C" \
    --request-rate inf --seed "$SEED" --flush-cache --output-details \
    --output-file "$OUT/input_16384_output_2048_concurrency$C.jsonl"
done
```

结果：未测。

## 3. Profiling

### PyTorch Profiler

宿主机执行：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/client
```

保存为 `/srv/inference/h20_glm-v53-flash_sglang_single/client/run_time_profile.py`：

```python
#!/usr/bin/env python3
"""Run one middle time window inside an SGLang service/client container."""
import argparse
import asyncio
import json
from pathlib import Path
import random
import urllib.request


def post(url, body, timeout):
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def get_workers(base_url):
    with urllib.request.urlopen(base_url.rstrip("/") + "/workers", timeout=10) as response:
        return json.load(response)


def pd_workers_ready(data, prefill_urls, decode_urls):
    workers = data.get("workers", [])
    return all(any(worker.get("url", "").rstrip("/") == url.rstrip("/")
                   and worker.get("worker_type") == role and worker.get("is_healthy") is True
                   for worker in workers)
               for role, urls in (("prefill", prefill_urls), ("decode", decode_urls))
               for url in urls)


def load_requests(args):
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
        input_len=args.isl, output_len=args.osl, num_prompts=5 * args.concurrency,
        range_ratio=1.0, tokenizer=tokenizer, dataset_path=str(dataset),
        random_sample=True, return_text=True)


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
    parser.add_argument("--request-timeout", type=int, default=1800)
    parser.add_argument("--control-timeout", type=int, default=1800)
    parser.add_argument("--ready-timeout", type=int, default=1800)
    parser.add_argument("--prerun-seconds", type=float, default=0)
    parser.add_argument("--prerun-completed-multiplier", type=int, default=4)
    parser.add_argument("--postrun-completed-multiplier", type=int, default=1)
    parser.add_argument("--capture-seconds", type=float, default=15)
    parser.add_argument("--max-requests", type=int, default=100000)
    args = parser.parse_args()
    if min(args.concurrency, args.isl, args.osl) < 1:
        parser.error("Concurrency and token lengths must be positive")
    if bool(args.prefill_url) != bool(args.decode_url):
        parser.error("PD requires both prefill and decode endpoints")
    from time_profile import TimeWindowRun
    TimeWindowRun(args, [None], post, get_workers, pd_workers_ready)
    asyncio.run(TimeWindowRun(args, load_requests(args), post, get_workers, pd_workers_ready).run())


if __name__ == "__main__":
    main()
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/client
```

保存为 `/srv/inference/h20_glm-v53-flash_sglang_single/client/time_profile.py`：

```python
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
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/client
```

保存为 `/srv/inference/h20_glm-v53-flash_sglang_single/client/validate_time_window.py`：

```python
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
```

single-node宿主机：

```bash
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/run_time_profile.py \
  --mode torch --concurrency 1 --base-url http://127.0.0.1:30000 \
  --model-path /models/GLM/GLM-5.3-Flash --model glm-53-flash \
  --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
  --isl 16384 --osl 2048 --seed 20277308 \
  --prerun-seconds 0 --prerun-completed-multiplier 4 --postrun-completed-multiplier 1 \
  --capture-seconds 15 --max-requests 100000 --prefix example-time \
  --output-dir /server/profiles/example-time-torch-C1
```

single-node宿主机：

```bash
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/validate_time_window.py /server/profiles/example-time-torch-C1 --role single --tp-size 8 --workload /server/profiles/example-time-torch-C1/workload.json
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/profiler/C1
cp -a /srv/inference/h20_glm-v53-flash_sglang_single/server/profiles/example-time-torch-C1/capture /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/profiler/C1/
cp /srv/inference/h20_glm-v53-flash_sglang_single/server/profiles/example-time-torch-C1/workload.json /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/profiler/C1/workload.json
```

结果：未测。

### Nsys

single-node宿主机：

```bash
docker stop h20_glm-v53-flash_sglang_single-client h20_glm-v53-flash_sglang_single-server
docker rm h20_glm-v53-flash_sglang_single-client h20_glm-v53-flash_sglang_single-server
docker pull lmsysorg/sglang:v0.5.21
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/{server/profiling_hooks,client}
docker run -d --name h20_glm-v53-flash_sglang_single-server \
  --runtime nvidia-container-runtime \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all \
  --mount type=bind,src=/sys,dst=/sys,readonly
  -p 30080:30000 --ipc=host \
  -v /srv/models:/models:ro \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/server:/server \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/client:/client \
  -w /server lmsysorg/sglang:v0.5.21 sleep infinity
docker run -d --name h20_glm-v53-flash_sglang_single-client \
  --network container:h20_glm-v53-flash_sglang_single-server \
  -v /srv/models:/models:ro -v /srv/datasets:/datasets:ro \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/server:/server \
  -v /srv/inference/h20_glm-v53-flash_sglang_single/client:/client \
  -w /client lmsysorg/sglang:v0.5.21 sleep infinity

docker exec h20_glm-v53-flash_sglang_single-server mkdir -p /server/profiles/example-time-nsys-C1/single
docker exec -d h20_glm-v53-flash_sglang_single-server nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --resolve-symbols=false --trace-fork-before-exec=true --cuda-graph-trace=node --capture-range=cudaProfilerApi --capture-range-end=repeat:sync --kill=none -o /server/profiles/example-time-nsys-C1/single/report sglang serve \
  --model-path /models/GLM/GLM-5.3-Flash --served-model-name glm-53-flash \
  --tp-size 8 --ep-size 8 --mem-fraction-static 0.75 \
  --dsa-prefill-backend tilelang --dsa-decode-backend tilelang \
  --kv-cache-dtype bfloat16 --moe-runner-backend deep_gemm \
  --host 0.0.0.0 --port 30000 --reasoning-parser auto --tool-call-parser auto \
  --disable-radix-cache
```

single-node宿主机：

```bash
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/check_ready.py
docker exec h20_glm-v53-flash_sglang_single-client python3 /client/run_time_profile.py \
  --mode nsys --concurrency 1 --base-url http://127.0.0.1:30000 \
  --model-path /models/GLM/GLM-5.3-Flash --model glm-53-flash \
  --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
  --isl 16384 --osl 2048 --seed 20277308 \
  --prerun-seconds 0 --prerun-completed-multiplier 4 --postrun-completed-multiplier 1 \
  --capture-seconds 15 --max-requests 100000 --prefix example-time \
  --output-dir /server/profiles/example-time-nsys-C1
```

single-node宿主机：

```bash
docker exec h20_glm-v53-flash_sglang_single-server bash -c 'set -euo pipefail; for report in /server/profiles/example-time-nsys-C1/single/*.nsys-rep; do test -s "$report"; nsys stats --report cuda_gpu_kern_sum,cuda_api_sum "$report"; done'
```

single-node宿主机：

```bash
mkdir -p /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/nsys/C1/capture
cp -a /srv/inference/h20_glm-v53-flash_sglang_single/server/profiles/example-time-nsys-C1/single /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/nsys/C1/capture/
cp /srv/inference/h20_glm-v53-flash_sglang_single/server/profiles/example-time-nsys-C1/workload.json /srv/inference/h20_glm-v53-flash_sglang_single/profiling_results/nsys/C1/workload.json
```

结果：未测。

