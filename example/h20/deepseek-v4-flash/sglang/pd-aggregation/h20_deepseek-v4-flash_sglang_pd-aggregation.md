# h20_deepseek-v4-flash_sglang_pd-aggregation

## 1. 启动服务

### 准备

prefill-node、decode-node为两机SSH别名；将文中的prefill.example.invalid、decode.example.invalid替换为两机互通IP。

```bash
# Linux、Docker及NVIDIA容器运行时已就绪
# 模型与tokenizer放入以下MODEL_DIR；两机相同
MODEL_DIR=/srv/models/Deepseek/DeepSeek-V4-Flash-0731
DATASET=/srv/datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json
test -r "$MODEL_DIR/config.json"
test -r "$MODEL_DIR/tokenizer_config.json"
test -r "$DATASET"
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
docker pull lmsysorg/sglang:v0.5.21
```

### prefill-node：Prefill，GPU4–7

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/{server,client}
docker pull lmsysorg/sglang:v0.5.21
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=4,5,6,7 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.90 --disable-radix-cache \
  --host 0.0.0.0 --port 30000 --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
```

### decode-node：Decode，GPU0–3

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/{server,client,runtime_cache/sglang}
docker pull lmsysorg/sglang:v0.5.21
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-decode \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=0,1,2,3 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/runtime_cache/sglang:/root/.cache/sglang \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.80 --disable-radix-cache \
  --host 0.0.0.0 --port 30080 --disaggregation-mode decode \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
```

### prefill-node：Router与客户端

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/pd_ready.py`：

```python
import json, time, urllib.request
expected = [("prefill", "http://prefill.example.invalid:30000"),
            ("decode", "http://decode.example.invalid:30080")]
deadline = time.monotonic() + 1800
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/workers", timeout=10) as response:
            workers = json.load(response).get("workers", [])
        if all(any(w.get("worker_type") == role and w.get("url", "").rstrip("/") == url
                   and w.get("is_healthy") is True for w in workers) for role, url in expected):
            print("prefill/decode healthy")
            break
    except (OSError, ValueError):
        pass
    if time.monotonic() >= deadline:
        raise TimeoutError("PD workers not ready")
    time.sleep(10)
```

```bash
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-router \
  --network host lmsysorg/sglang:v0.5.21 \
  python3 -m sglang_router.launch_router --pd-disaggregation \
  --prefill http://prefill.example.invalid:30000 --decode http://decode.example.invalid:30080 \
  --host 0.0.0.0 --port 8000

docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  --network host -v /srv/models:/models:ro \
  -v /srv/datasets:/datasets:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -w /server lmsysorg/sglang:v0.5.21 sleep infinity

docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/pd_ready.py
```

结果：Prefill、Decode均healthy。

### 对话验证（prefill-node）

```bash
test -r /srv/models/Deepseek/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/chat_test.py`：

```python
import importlib.util
import json
import sys
import urllib.request

port, model, encoder_path = sys.argv[1:]
spec = importlib.util.spec_from_file_location("encoding_dsv4", encoder_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load official encoder: {encoder_path}")
encoding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(encoding)

messages = [{"role": "user", "content": "Hello"}]
prompt = encoding.encode_messages(messages, thinking_mode="chat")
payload = {
    "model": model,
    "prompt": prompt,
    "temperature": 0.0,
    "top_p": 1.0,
    "max_tokens": 128,
    "stop": [encoding.eos_token],
}
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/completions",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=300) as response:
    result = json.loads(response.read().decode("utf-8"))

if result.get("model") != model:
    raise RuntimeError(f"Unexpected response model: {result.get('model')!r}")
choices = result.get("choices")
if not isinstance(choices, list) or not choices:
    raise RuntimeError("Response does not contain choices")
text = choices[0].get("text")
if not isinstance(text, str) or not text.strip():
    raise RuntimeError("Model returned empty completion text")
if choices[0].get("finish_reason") != "stop":
    raise RuntimeError(f"Completion did not reach the official stop token: {choices[0].get('finish_reason')!r}")

parsed = encoding.parse_message_from_completion_text(
    text + encoding.eos_token,
    thinking_mode="chat",
)
if not parsed.get("content", "").strip():
    raise RuntimeError("Official decoder produced empty assistant content")

print(json.dumps({
    "request": {"endpoint": "/v1/completions", "messages": messages, "thinking_mode": "chat"},
    "assistant": parsed,
    "raw_response": result,
}, ensure_ascii=False, indent=2))
```

```bash
docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/chat_test.py 8000 deepseek-v4-flash /models/Deepseek/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py
```

结果：Hello! How can I help you today?；model=deepseek-v4-flash，finish_reason=stop，输入5/输出10 token。

## 2. Baseline压测

### 压测命令（prefill-node）

```bash
set -euo pipefail
CLIENT=h20_deepseek-v4-flash_sglang_pd-aggregation-client
OUT=/tmp/tuning-20261021-baseline-results
docker exec "$CLIENT" mkdir -p "$OUT"
for C in 1 8 32; do
  N=$((C * 5))
  SEED=$((20260923 + 16384 + C))
  docker exec "$CLIENT" bash -o pipefail -c '
    python3 -m sglang.bench_serving \
      --backend sglang --host 127.0.0.1 --port 8000 \
      --model deepseek-v4-flash \
      --tokenizer /models/Deepseek/DeepSeek-V4-Flash-0731 \
      --dataset-name random --random-range-ratio 1.0 --flush-cache \
      --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
      --random-input-len 16384 --random-output-len 2048 \
      --warmup-requests 2 --num-prompts "$1" --max-concurrency "$2" \
      --seed "$3" --output-file "$4/C$2.jsonl" 2>&1 | tee "$4/C$2.log"
  ' bash "$N" "$C" "$SEED" "$OUT"
done
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/baseline/benchmark
docker cp "$CLIENT:$OUT/." /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/baseline/benchmark/
```

### 基线结果

| C | 成功数 | 总tok/s | 输出tok/s | 输出tok/s/GPU¹ | TTFT平均/P50/P99 (ms) | TPOT平均/P50/P99 (ms) |
|---:|---:|---:|---:|---:|---|---|
| 1 | 5/5 | 1577.53 | 175.28 | 21.91 | 7323.16/5838.11/12969.54 | 2.129/2.074/2.254 |
| 8 | 40/40 | 6031.98 | 670.22 | 83.78 | 15837.10/15157.58/29213.85 | 3.406/3.440/5.240 |
| 32 | 160/160 | 8744.32 | 971.59 | 121.45 | 53333.84/55468.34/72003.47 | 3.688/3.714/5.197 |

¹ TPS/GPU按整个1P1D的8张卡折算。
结果：205/205成功；三档输入token=81920/655360/2621440，输出token=10240/81920/327680。14分24秒。仅测C1/8/32，未测C2/4/16。

## 3. Profiling

### PyTorch Profiler

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/run_time_profile.py`：

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
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/time_profile.py`：

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
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/validate_time_window.py`：

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

prefill-node宿主机：

```bash
ssh decode-node 'mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16'
scp /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/validate_time_window.py decode-node:/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/validate_time_window.py
```

prefill-node宿主机：

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/run_time_profile.py \
  --mode torch --concurrency 16 --base-url http://127.0.0.1:8000 \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --model deepseek-v4-flash \
  --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
  --isl 16384 --osl 2048 --seed 20277323 \
  --prerun-seconds 0 --prerun-completed-multiplier 4 --postrun-completed-multiplier 1 \
  --capture-seconds 15 --max-requests 100000 --prefix example-time \
  --output-dir /server/profiles/example-time-torch-C16 \
  --prefill-url http://prefill.example.invalid:30000 \
  --decode-url http://decode.example.invalid:30080
```

prefill-node宿主机：

```bash
scp /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/workload.json decode-node:/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/workload.json
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-prefill python3 /client/validate_time_window.py /server/profiles/example-time-torch-C16 --role prefill --tp-size 4 --workload /server/profiles/example-time-torch-C16/workload.json
```

decode-node宿主机：

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-decode python3 /client/validate_time_window.py /server/profiles/example-time-torch-C16 --role decode --tp-size 4 --workload /server/profiles/example-time-torch-C16/workload.json
```

prefill-node宿主机，汇集两角色原生结果：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/profiler/C16
ssh decode-node 'tar -C /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/capture -czf /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/decode.tar.gz decode'
scp decode-node:/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/decode.tar.gz /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/decode.tar.gz
tar -xzf /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/decode.tar.gz -C /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/capture
cp -a /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/capture /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/profiler/C16/
cp /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-torch-C16/workload.json /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/profiler/C16/workload.json
```

结果：未测。

### Nsys

prefill-node宿主机：

```bash
docker stop h20_deepseek-v4-flash_sglang_pd-aggregation-prefill
docker rm h20_deepseek-v4-flash_sglang_pd-aggregation-prefill
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/prefill
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/{server,client}
docker pull lmsysorg/sglang:v0.5.21
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=4,5,6,7 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --resolve-symbols=false --trace-fork-before-exec=true --cuda-graph-trace=node --capture-range=cudaProfilerApi --capture-range-end=repeat:sync --kill=none -o /server/profiles/example-time-nsys-C16/prefill/report sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.90 --disable-radix-cache \
  --host 0.0.0.0 --port 30000 --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
```

decode-node宿主机：

```bash
docker stop h20_deepseek-v4-flash_sglang_pd-aggregation-decode
docker rm h20_deepseek-v4-flash_sglang_pd-aggregation-decode
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/decode
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/{server,client,runtime_cache/sglang}
docker pull lmsysorg/sglang:v0.5.21
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-decode \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=0,1,2,3 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/runtime_cache/sglang:/root/.cache/sglang \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --resolve-symbols=false --trace-fork-before-exec=true --cuda-graph-trace=node --capture-range=cudaProfilerApi --capture-range-end=repeat:sync --kill=none -o /server/profiles/example-time-nsys-C16/decode/report sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.80 --disable-radix-cache \
  --host 0.0.0.0 --port 30080 --disaggregation-mode decode \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
```

prefill-node宿主机：

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/pd_ready.py
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/run_time_profile.py \
  --mode nsys --concurrency 16 --base-url http://127.0.0.1:8000 \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --model deepseek-v4-flash \
  --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
  --isl 16384 --osl 2048 --seed 20277323 \
  --prerun-seconds 0 --prerun-completed-multiplier 4 --postrun-completed-multiplier 1 \
  --capture-seconds 15 --max-requests 100000 --prefix example-time \
  --output-dir /server/profiles/example-time-nsys-C16 \
  --prefill-url http://prefill.example.invalid:30000 \
  --decode-url http://decode.example.invalid:30080
```

prefill-node宿主机：

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-prefill bash -c 'set -euo pipefail; for report in /server/profiles/example-time-nsys-C16/prefill/*.nsys-rep; do test -s "$report"; nsys stats --report cuda_gpu_kern_sum,cuda_api_sum "$report"; done'
```

decode-node宿主机：

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-decode bash -c 'set -euo pipefail; for report in /server/profiles/example-time-nsys-C16/decode/*.nsys-rep; do test -s "$report"; nsys stats --report cuda_gpu_kern_sum,cuda_api_sum "$report"; done'
```

prefill-node宿主机：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/nsys/C16/capture
cp -a /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/prefill /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/nsys/C16/capture/
ssh decode-node 'tar -C /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16 -czf /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/decode.tar.gz decode'
scp decode-node:/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/decode.tar.gz /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/decode.tar.gz
tar -xzf /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/decode.tar.gz -C /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/nsys/C16/capture
cp /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/profiles/example-time-nsys-C16/workload.json /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/profiling_results/nsys/C16/workload.json
```

结果：未测。

## 4. 优化1：配置、框架与算子联合优化

### 4.1 优化策略

| 方面 | 修改 | 预期作用 |
|---|---|---|
| 配置 | P chunk 4096→8192、显存比例0.90→0.88；D不变 | 减少prefill切分，留出较大chunk的运行余量 |
| 框架 | hc_pre的eager闭包只创建一次；capture编译包装首次建立后缓存 | 减少重复Python对象和包装创建，保留capture语义 |
| 算子 | BF16、宽1024、行4096/8192使用4行/CTA Triton RMSNorm；其余保留原实现 | 降低目标形状的归约开销；不预设端到端收益 |

### 4.2 源码与验证文件

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/operators
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/operators/grouped_rmsnorm.py`：

```python
"""Joint candidate: four rows per CTA for medium-width prefill RMSNorm.

Small/decode shapes and fused residual paths retain the installed implementation.
Implicit Hopper PDL optimization is not retained on this experimental branch;
explicit enable_pdl=True is left to the original implementation.
"""
import torch
import triton
import triton.language as tl

_announced = False

@triton.jit
def grouped_rms_kernel(X, W, Y, M: tl.constexpr, N: tl.constexpr,
                       SX: tl.constexpr, SY: tl.constexpr, EPS: tl.constexpr,
                       BLOCK: tl.constexpr, ROWS: tl.constexpr):
    rows = tl.program_id(0) * ROWS + tl.arange(0, ROWS)
    cols = tl.arange(0, BLOCK)
    x = tl.load(X + rows[:, None] * SX + cols[None, :],
                (rows[:, None] < M) & (cols[None, :] < N), other=0).to(tl.float32)
    w = tl.load(W + cols, cols < N, other=0).to(tl.float32)
    inv = tl.rsqrt(tl.sum(x * x, axis=1) / N + EPS)
    y = x * inv[:, None] * w[None, :]
    tl.store(Y + rows[:, None] * SY + cols[None, :], y,
             (rows[:, None] < M) & (cols[None, :] < N))

def rmsnorm(x, weight, eps=1e-6, out=None):
    global _announced
    if out is None:
        out = torch.empty_like(x)
    grouped_rms_kernel[(triton.cdiv(x.shape[0], 4),)](
        x, weight, out, x.shape[0], x.shape[1], x.stride(0), out.stride(0),
        eps, triton.next_power_of_2(x.shape[1]), 4, num_warps=4)
    if not _announced and not torch.cuda.is_current_stream_capturing():
        print(f'JOINT_OPERATOR=grouped-rmsnorm-v1 shape={tuple(x.shape)}', flush=True)
        _announced = True
    return out
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/test_candidate.py`：

```python
"""CPU framework equivalence and post-baseline GPU norm checks; no service edits."""
import argparse
import ast
import json
from pathlib import Path
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parent

def framework_check():
    tree = ast.parse((ROOT / "framework/deepseek_v4.py").read_text())
    factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_make_hc_pre_torch_impl")
    decorations = []
    def compile_stub(func):
        decorations.append(func)
        return func
    namespace = {"torch": torch, "F": F, "compile_in_capture_mode": compile_stub}
    exec(compile(ast.Module(body=[factory], type_ignores=[]), "candidate-factory", "exec"), namespace)
    helper = namespace["_make_hc_pre_torch_impl"](1e-6)
    torch.manual_seed(123)
    for rows in (1, 16, 128):
        x = torch.randn(rows, 4, 32, dtype=torch.bfloat16)
        weight = torch.randn(24, 128)
        flat, mixes = helper(x, weight)
        ref = x.flatten(1).float()
        expected = (F.linear(ref, weight) * torch.rsqrt(ref.square().mean(-1, keepdim=True) + 1e-6)).unsqueeze(1)
        torch.testing.assert_close(flat, ref, atol=0, rtol=0)
        torch.testing.assert_close(mixes, expected, atol=0, rtol=0)
    assert len(decorations) == 0, "eager initialization must not invoke capture decorator"
    from types import SimpleNamespace
    layer = SimpleNamespace(_hc_pre_torch_impl=helper, _hc_pre_capture_impl=None)
    hc_pre = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "hc_pre")
    selection = next(node for node in hc_pre.body if isinstance(node, ast.If)
                     and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name)
                     and node.test.func.id == "get_is_capture_mode")
    for capture in (False, False, True, True, False, True):
        namespace.update(self=layer, get_is_capture_mode=lambda: capture)
        exec(compile(ast.Module(body=[selection], type_ignores=[]), "phase-selection", "exec"), namespace)
        assert namespace["hc_pre_torch_impl"] is helper
    assert len(decorations) == 1, "compile wrapper should be created on first capture only"
    print(json.dumps({"framework_cpu_cases": 3, "phase_selection_cases": 6, "wrapper_constructions": len(decorations),
                      "limitation": "AST function behavior; real installed decorator/model loading still requires service validation"}))

def kernel_check():
    import sys
    sys.path.insert(0, str(ROOT / "operators"))
    from grouped_rmsnorm import rmsnorm
    from flashinfer.norm import rmsnorm as original
    torch.manual_seed(42)
    cases = []
    timings = []
    for dtype in (torch.float16, torch.bfloat16):
        for rows in (128, 129, 512, 4096, 8192):
            for width in (512, 1024, 2048):
                # Strided rows emulate fused QKV slices; columns stay contiguous.
                backing = torch.randn(rows, width + 128, device="cuda", dtype=dtype)
                x = backing[:, :width]
                weight = torch.randn(width, device="cuda", dtype=dtype)
                y = rmsnorm(x, weight)
                baseline = original(x, weight)
                reference = (x.float() * torch.rsqrt(x.float().square().mean(-1, keepdim=True) + 1e-6) * weight.float()).to(dtype)
                atol = 0.03125 if dtype == torch.bfloat16 else 0.004
                torch.testing.assert_close(y, reference, atol=atol, rtol=0.01)
                torch.testing.assert_close(y, baseline, atol=atol, rtol=0.01)
                out = torch.empty(rows, width + 64, device="cuda", dtype=dtype)[:, :width]
                assert rmsnorm(x, weight, out=out).data_ptr() == out.data_ptr()
                torch.testing.assert_close(out, y, atol=0, rtol=0)
                cases.append({"rows": rows, "width": width, "dtype": str(dtype),
                              "max_abs_difference": (y.float() - baseline.float()).abs().max().item()})
                if dtype == torch.bfloat16 and width == 1024 and rows in (128, 4096, 8192):
                    def elapsed(func):
                        for _ in range(10):
                            func(x, weight, out=out)
                        start = torch.cuda.Event(enable_timing=True)
                        finish = torch.cuda.Event(enable_timing=True)
                        start.record()
                        for _ in range(100):
                            func(x, weight, out=out)
                        finish.record()
                        finish.synchronize()
                        return start.elapsed_time(finish) * 1000 / 100
                    timings.append({"rows": rows, "width": width,
                                    "baseline_us": elapsed(original), "candidate_us": elapsed(rmsnorm)})
    print(json.dumps({"gpu_cases": len(cases), "cases": cases,
                      "microbenchmark": timings, "microbenchmark_scope": "Isolated CUDA-event loop, not model-serving benefit"}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    framework_check()
    if args.gpu:
        kernel_check()
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/graph_microbench.py`：

```python
"""Bounded CUDA Graph microbenchmark; no serving performance conclusion."""
import json
from pathlib import Path
import sys
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent / "operators"))
from grouped_rmsnorm import rmsnorm as candidate
from flashinfer.norm import rmsnorm as baseline

def measure(func, x, weight, out):
    for _ in range(20):
        func(x, weight, out=out)
    torch.cuda.synchronize()
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.graph(graph):
        for _ in range(100):
            func(x, weight, out=out)
    for _ in range(5):
        graph.replay()
    start = torch.cuda.Event(enable_timing=True)
    finish = torch.cuda.Event(enable_timing=True)
    start.record()
    for _ in range(20):
        graph.replay()
    finish.record()
    finish.synchronize()
    return start.elapsed_time(finish) * 1000 / 2000

torch.manual_seed(42)
rows = []
for count in (128, 4096, 8192):
    x = torch.randn(count, 1152, dtype=torch.bfloat16, device="cuda")[:, :1024]
    w = torch.randn(1024, dtype=torch.bfloat16, device="cuda")
    out = torch.empty(count, 1088, dtype=torch.bfloat16, device="cuda")[:, :1024]
    rows.append({"rows": count, "width": 1024,
                 "baseline_graph_us": measure(baseline, x, w, out),
                 "candidate_graph_us": measure(candidate, x, w, out)})
print(json.dumps({"measurements": rows, "scope": "100 operations per graph, 20 replays, isolated BF16/strided input and out; not serving throughput"}))
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/test_dispatch.py`：

```python
"""Validate final dispatch guards against real installed FlashInfer on the GPU."""
import importlib.util
import json
from pathlib import Path
import sys
import torch
from flashinfer.norm import rmsnorm as original

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "operators"))
import grouped_rmsnorm
real = grouped_rmsnorm.rmsnorm
calls = []
def record(*args, **kwargs):
    calls.append(tuple(args[0].shape))
    return real(*args, **kwargs)
grouped_rmsnorm.rmsnorm = record
spec = importlib.util.spec_from_file_location("joint_elementwise", ROOT / "operators/elementwise.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
torch.manual_seed(42)
cases = []
for dtype in (torch.bfloat16, torch.float16):
    for rows in (128, 4096, 8192):
        for width in (512, 1024):
            x = torch.randn(rows, width + 128, dtype=dtype, device="cuda")[:, :width]
            weight = torch.randn(width, dtype=dtype, device="cuda")
            before = len(calls)
            y = module.rmsnorm(x, weight)
            expected = original(x, weight)
            use_new = dtype == torch.bfloat16 and rows in (4096, 8192) and width == 1024
            assert (len(calls) > before) == use_new
            torch.testing.assert_close(y, expected, atol=0.03125 if dtype == torch.bfloat16 else 0.004, rtol=0.01)
            cases.append({"rows": rows, "width": width, "dtype": str(dtype), "new_kernel": use_new})
x = torch.randn(4096, 1024, dtype=torch.bfloat16, device="cuda")
weight = torch.randn(1024, dtype=torch.bfloat16, device="cuda")
before = len(calls)
y = module.rmsnorm(x, weight, enable_pdl=True)
assert len(calls) == before, "explicit PDL must retain installed dispatch"
torch.testing.assert_close(y, original(x, weight, enable_pdl=True), atol=0, rtol=0)
print(json.dumps({"dispatch_cases": len(cases) + 1, "new_kernel_calls": len(calls), "cases": cases}))
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/operators
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/operators/experiment_rmsnorm.py`：

```python
"""Experimental GPU RMSNorm implementation, not a performance claim.

One Triton program per row; FP32 reduction and product, output in input dtype.
Only the standard unfused RMSNorm path is replaced. Fused residual paths remain
the installed baseline. This module is loaded only by the operator variant.
"""
import torch
import triton
import triton.language as tl

_announced = False

@triton.jit
def experimental_rmsnorm_kernel(X, W, Y, SX: tl.constexpr, SY: tl.constexpr,
                               N: tl.constexpr, EPS: tl.constexpr,
                               BLOCK: tl.constexpr):
    row = tl.program_id(0)
    col = tl.arange(0, BLOCK)
    x = tl.load(X + row * SX + col, col < N, other=0).to(tl.float32)
    w = tl.load(W + col, col < N, other=0).to(tl.float32)
    inv_rms = tl.rsqrt(tl.sum(x * x, axis=0) / N + EPS)
    tl.store(Y + row * SY + col, x * inv_rms * w, col < N)

def rmsnorm(input, weight, eps=1e-6, out=None, enable_pdl=None):
    global _announced
    if input.ndim != 2 or input.stride(-1) != 1 or weight.ndim != 1:
        raise ValueError('Experimental RMSNorm requires 2D input and contiguous columns')
    if input.shape[1] != weight.numel() or not weight.is_contiguous():
        raise ValueError('Experimental RMSNorm weight shape/stride mismatch')
    if not input.is_cuda or input.dtype not in (torch.float16, torch.bfloat16):
        raise ValueError('Experimental RMSNorm supports CUDA FP16/BF16 only')
    if out is None:
        out = torch.empty_like(input)
    if out.shape != input.shape or out.stride(-1) != 1 or out.dtype != input.dtype:
        raise ValueError('Experimental RMSNorm output shape/stride/dtype mismatch')
    if input.shape[0]:
        block = triton.next_power_of_2(input.shape[1])
        experimental_rmsnorm_kernel[(input.shape[0],)](
            input, weight, out, input.stride(0), out.stride(0), input.shape[1],
            eps, block, num_warps=4 if block <= 2048 else 8)
        if not _announced:
            print(f'OPERATOR_VARIANT=triton-rmsnorm-v1 shape={tuple(input.shape)} dtype={input.dtype}', flush=True)
            _announced = True
    return out
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/operators
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/operators/test_rmsnorm.py`：

```python
import json
import torch
from flashinfer.norm import rmsnorm as baseline
from experiment_rmsnorm import rmsnorm

def main():
    torch.manual_seed(42)
    results = []
    for dtype in (torch.float16, torch.bfloat16):
        for rows in (1, 16, 128):
            for hidden in (128, 512, 1024, 4096, 7168):
                x = torch.randn((rows, hidden), device='cuda', dtype=dtype)
                w = torch.randn(hidden, device='cuda', dtype=dtype)
                actual = rmsnorm(x, w)
                expected = baseline(x, w)
                reference = (x.float() * torch.rsqrt(x.float().square().mean(-1, keepdim=True) + 1e-6) * w.float()).to(dtype)
                atol = 0.03125 if dtype == torch.bfloat16 else 0.004
                torch.testing.assert_close(actual, reference, atol=atol, rtol=0.01)
                torch.testing.assert_close(actual, expected, atol=atol, rtol=0.01)
                out = torch.empty_like(x)
                assert rmsnorm(x, w, out=out).data_ptr() == out.data_ptr()
                torch.testing.assert_close(out, actual, atol=0, rtol=0)
                results.append({'dtype': str(dtype), 'rows': rows, 'hidden': hidden,
                                'max_abs_diff_vs_baseline': (actual.float()-expected.float()).abs().max().item()})
    torch.cuda.synchronize()
    print(json.dumps({'passed': len(results), 'cases': results}, indent=2))

if __name__ == '__main__':
    main()
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/framework
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/framework/test_middleware.py`：

```python
"""Execute the exact added function without booting a GPU model or importing SGLang."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

async def main():
    tree = ast.parse(Path(__file__).with_name('http_server.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'experiment_source_variant_header')
    node.decorator_list = []
    logged = []
    scope = {'Request': object, 'logger': SimpleNamespace(warning=lambda *a: logged.append(a))}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-middleware-source>', 'exec'), scope)
    for path in ('/health', '/generate', '/v1/completions', '/v1/chat/completions'):
        response = SimpleNamespace(headers={'content-type': 'application/json'}, status_code=200)
        async def call_next(request):
            return response
        result = await scope['experiment_source_variant_header'](
            SimpleNamespace(url=SimpleNamespace(path=path)), call_next)
        assert result is response
        assert result.headers['X-Experiment-Variant'] == 'framework-source-v1'
        assert result.headers['content-type'] == 'application/json'
    assert len(logged) == 3
    print('4 actual-source middleware behavior cases passed; no GPU service validation implied.')

if __name__ == '__main__':
    asyncio.run(main())
```

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/prepare_sources.py`：

```python
from pathlib import Path
import hashlib

def replace_source(source, destination, expected_original, expected_modified, edits):
    text = Path(source).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode()).hexdigest() == expected_original, source
    lines = text.splitlines(keepends=True)
    for start, end, replacement in reversed(edits):
        lines[start:end] = replacement.splitlines(keepends=True)
    result = "".join(lines)
    assert hashlib.sha256(result.encode()).hexdigest() == expected_modified, destination
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result, encoding="utf-8")

replace_source(
    "/opt/sglang/lib/python3.12/site-packages/sgl_kernel/elementwise.py",
    "/server/source_overrides/operators/elementwise.py",
    "88e15c6ec7266ed2564151fb8b072d23a8375978f15a8c9b768d5fa16d279ca9",
    "f5f18dc043bf526c64af2cd7e0c5086c50c5ca23cf0ab0856defe8043c6066c6",
    [
        (119, 120, '''        # Isolated source experiment: replace the actual GPU implementation.
        from experiment_rmsnorm import rmsnorm as experimental_rmsnorm

        return experimental_rmsnorm(input, weight, eps, out, enable_pdl)
'''),
    ],
)

replace_source(
    "/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py",
    "/server/source_overrides/framework/http_server.py",
    "1fbb46671e86d0ebf23046efa09e8e03d251754e681ba03b818dbb7a75c79c55",
    "8dde2adfc39fe41be482c2c6f86ac0fd3b5642bbc80a86aff32526f5782881f4",
    [
        (479, 479, '''

@app.middleware("http")
async def experiment_source_variant_header(request: Request, call_next):
    """Isolated framework-source validation; no model or scheduling changes."""
    response = await call_next(request)
    response.headers["X-Experiment-Variant"] = "framework-source-v1"
    if request.url.path in ("/generate", "/v1/completions", "/v1/chat/completions"):
        logger.warning("FRAMEWORK_VARIANT=framework-source-v1 path=%s status=%s",
                       request.url.path, response.status_code)
    return response

'''),
    ],
)

replace_source(
    "/opt/sglang/lib/python3.12/site-packages/sgl_kernel/elementwise.py",
    "/candidate/operators/elementwise.py",
    "88e15c6ec7266ed2564151fb8b072d23a8375978f15a8c9b768d5fa16d279ca9",
    "bdb4727f1892efd5c87a044f90f6fb3ca25afc30e552515c9f4ab3b2e8e94f23",
    [
        (119, 119, '''        if (
            input.is_cuda
            and input.ndim == 2
            and input.dtype == torch.bfloat16
            and input.shape[0] in (4096, 8192)
            and input.shape[1] == 1024
            and input.stride(1) == 1
            and weight.ndim == 1
            and weight.numel() == input.shape[1]
            and weight.is_contiguous()
            and weight.device == input.device
            and weight.dtype == input.dtype
            and enable_pdl is not True
            and (out is None or (out.shape == input.shape and out.stride(1) == 1
                                 and out.dtype == input.dtype and out.device == input.device))
        ):
            from grouped_rmsnorm import rmsnorm
            return rmsnorm(input, weight, eps, out)
'''),
    ],
)

replace_source(
    "/sgl-workspace/sglang/python/sglang/srt/models/deepseek_v4.py",
    "/candidate/framework/deepseek_v4.py",
    "8e20dcfded3345228eed07effe32d4fb3c25a66af00b44af9627b16b101f1f78",
    "236b69ed397d7dcbfe7626e0c7515609c430361a56c0c16167bb9745c560ab5c",
    [
        (529, 529, '''

def _make_hc_pre_torch_impl(rms_norm_eps):
    # Construct the eager closure once; compile lazily inside capture mode only.
    # Hoisting the original decorator into __init__ would change its semantics.
    def hc_pre_torch_impl(x, hc_fn):
        x_flat = x.flatten(1).float()
        rsqrt = torch.rsqrt(
            x_flat.square().mean(-1, keepdim=True) + rms_norm_eps
        )
        mixes = (F.linear(x_flat, hc_fn) * rsqrt).unsqueeze(1)
        return x_flat, mixes

    return hc_pre_torch_impl
'''),
        (2673, 2673, '''        self._hc_pre_torch_impl = _make_hc_pre_torch_impl(self.rms_norm_eps)
        self._hc_pre_capture_impl = None
        if layer_id == 0:
            print("JOINT_FRAMEWORK=hc-pre-phase-cache-v1", flush=True)
'''),
        (2773, 2781, '''        if get_is_capture_mode():
            if self._hc_pre_capture_impl is None:
                self._hc_pre_capture_impl = compile_in_capture_mode(self._hc_pre_torch_impl)
            hc_pre_torch_impl = self._hc_pre_capture_impl
        else:
            hc_pre_torch_impl = self._hc_pre_torch_impl
'''),
    ],
)
```

```bash
docker run --rm --network none \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client:ro \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source:/candidate \
  lmsysorg/sglang:v0.5.21 python3 /client/prepare_sources.py
```

### 4.3 单独替换的功能验证

#### 算子替换（prefill-node）

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  python3 /server/source_overrides/operators/test_rmsnorm.py
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=4,5,6,7 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -e PYTHONPATH=/server/source_overrides/operators:/sgl-workspace/sglang/python \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/operators/elementwise.py:/opt/sglang/lib/python3.12/site-packages/sgl_kernel/elementwise.py:ro \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.90 --disable-radix-cache \
  --host 0.0.0.0 --port 30000 --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/pd_ready.py
docker logs h20_deepseek-v4-flash_sglang_pd-aggregation-prefill 2>&1 | grep -E OPERATOR_VARIANT
```

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/pd_ready.py
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/chat_test.py 8000 deepseek-v4-flash /models/Deepseek/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py
```

结果：30组数值用例通过，max_abs_diff=0.0078125；四TP实际shape=(256,1024)、BF16；Hello通过。

#### 框架替换（prefill-node）

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  python3 /server/source_overrides/framework/test_middleware.py
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=4,5,6,7 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server/source_overrides/framework/http_server.py:/sgl-workspace/sglang/python/sglang/srt/entrypoints/http_server.py:ro \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 4096 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.90 --disable-radix-cache \
  --host 0.0.0.0 --port 30000 --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/pd_ready.py
curl --fail -i http://127.0.0.1:30000/health
docker logs h20_deepseek-v4-flash_sglang_pd-aggregation-prefill 2>&1 | grep -E FRAMEWORK_VARIANT
```

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/pd_ready.py
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/chat_test.py 8000 deepseek-v4-flash /models/Deepseek/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py
```

结果：4项行为测试通过；响应头X-Experiment-Variant: framework-source-v1，生成请求日志status=200；Hello通过。两项单独验证仅证明替换可用，未测独立性能。

### 4.4 联合版本验证与压测

#### 数值、分派与微测：prefill-node，基线压测结束后

```bash
docker cp /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source h20_deepseek-v4-flash_sglang_pd-aggregation-prefill:/tmp/joint-source-gpu
docker exec -e CUDA_VISIBLE_DEVICES=4 h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  /opt/sglang/bin/python /tmp/joint-source-gpu/test_candidate.py --gpu
docker exec -e CUDA_VISIBLE_DEVICES=4 h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  /opt/sglang/bin/python /tmp/joint-source-gpu/test_dispatch.py
docker exec -e CUDA_VISIBLE_DEVICES=4 h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  /opt/sglang/bin/python /tmp/joint-source-gpu/graph_microbench.py
```

结果：框架3数值/6phase、算子30参数+30次out、13分派用例通过；max_abs_diff=0.03125。Graph局部4096行4.35→4.03μs、8192行7.87→6.79μs；普通Event微测更慢，不能把局部收益当服务收益。

#### 联合版本启动：prefill-node

```bash
docker run -d --name h20_deepseek-v4-flash_sglang_pd-aggregation-prefill \
  --runtime nvidia-container-runtime -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=all -e CUDA_VISIBLE_DEVICES=4,5,6,7 \
  --network host --ipc=host --shm-size 32g \
  -v /dev/infiniband:/dev/infiniband -v /sys:/sys:ro \
  -v /srv/models:/models:ro -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/server:/server \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client:/client \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source:/candidate:ro \
  -e PYTHONPATH=/candidate/operators:/sgl-workspace/sglang/python \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/framework/deepseek_v4.py:/sgl-workspace/sglang/python/sglang/srt/models/deepseek_v4.py:ro \
  -v /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/source/operators/elementwise.py:/opt/sglang/lib/python3.12/site-packages/sgl_kernel/elementwise.py:ro \
  -w /server lmsysorg/sglang:v0.5.21 \
  env PROFILE_HOOK_ENABLED=0 SGLANG_PROFILE_V2=0 \
  sglang serve --trust-remote-code \
  --model-path /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tp 4 --moe-runner-backend flashinfer_mxfp4 --speculative-algorithm DSPARK \
  --chunked-prefill-size 8192 --swa-full-tokens-ratio 0.1 \
  --mem-fraction-static 0.88 --disable-radix-cache \
  --host 0.0.0.0 --port 30000 --disaggregation-mode prefill \
  --disaggregation-transfer-backend mooncake \
  --disaggregation-ib-device mlx5_0,mlx5_1,mlx5_2,mlx5_3,mlx5_4
docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client python3 /client/pd_ready.py
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 -m sglang.bench_serving --backend sglang --host 127.0.0.1 --port 8000 \
  --model /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
  --tokenizer /models/Deepseek/DeepSeek-V4-Flash-0731 \
  --dataset-name random --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
  --random-range-ratio 1.0 --random-input-len 16384 --random-output-len 1 \
  --flush-cache --warmup-requests 0 --num-prompts 1 --max-concurrency 1 --seed 20277308 \
  --output-file /tmp/joint-v1-long-validation.jsonl

docker logs h20_deepseek-v4-flash_sglang_pd-aggregation-prefill 2>&1 | grep -E 'JOINT_FRAMEWORK|JOINT_OPERATOR'
```

```bash
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/pd_ready.py
docker exec h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/chat_test.py 8000 deepseek-v4-flash /models/Deepseek/DeepSeek-V4-Flash-0731/encoding/encoding_dsv4.py
```

结果：四TP真实模型调用shape=(8192,1024)，框架/算子标记齐全，Hello通过。

#### 联合版本压测（prefill-node）

```bash
set -euo pipefail
CLIENT=h20_deepseek-v4-flash_sglang_pd-aggregation-client
OUT=/tmp/tuning-20261021-joint-v1-results
docker exec "$CLIENT" mkdir -p "$OUT"
for C in 1 8 32; do
  N=$((C * 5))
  SEED=$((20260923 + 16384 + C))
  docker exec "$CLIENT" bash -o pipefail -c '
    python3 -m sglang.bench_serving \
      --backend sglang --host 127.0.0.1 --port 8000 \
      --model /models/Deepseek/DeepSeek-V4-Flash-0731 --served-model-name deepseek-v4-flash \
      --tokenizer /models/Deepseek/DeepSeek-V4-Flash-0731 \
      --dataset-name random --random-range-ratio 1.0 --flush-cache \
      --dataset-path /datasets/ShareGPT_Vicuna_unfiltered/ShareGPT_V3_unfiltered_cleaned_split.json \
      --random-input-len 16384 --random-output-len 2048 \
      --warmup-requests 2 --num-prompts "$1" --max-concurrency "$2" \
      --seed "$3" --output-file "$4/C$2.jsonl" 2>&1 | tee "$4/C$2.log"
  ' bash "$N" "$C" "$SEED" "$OUT"
done
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/benchmark
docker cp "$CLIENT:$OUT/." /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/tuning/20261021-joint-c1-c8-c32/candidates/joint-v1/benchmark/
```

| C | 成功数 | 总tok/s | 输出tok/s | 输出tok/s/GPU¹ | TTFT平均/P50/P99 (ms) | TPOT平均/P50/P99 (ms) |
|---:|---:|---:|---:|---:|---|---|
| 1 | 5/5 | 1579.77 | 175.53 | 21.94 | 7321.76/5799.10/13054.98 | 2.121/2.075/2.228 |
| 8 | 40/40 | 6095.18 | 677.24 | 84.66 | 16071.99/17708.83/28586.76 | 3.428/3.604/4.921 |
| 32 | 160/160 | 8996.36 | 999.60 | 124.95 | 51413.02/52990.07/70456.60 | 3.868/3.860/5.917 |

¹ TPS/GPU按整个1P1D的8张卡折算。

#### 验收与逐档比较：prefill-node

宿主机执行：

```bash
mkdir -p /srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client
```

保存为 `/srv/inference/h20_deepseek-v4-flash_sglang_pd-aggregation/client/compare_results.py`：

```python
"""Validate or compare the study's real SGLang serving JSONL, no workload launch."""
import argparse
import json
import math
from pathlib import Path

METRICS = ("output_throughput", "total_throughput", "request_throughput", "mean_ttft_ms", "median_ttft_ms", "p95_ttft_ms",
           "p99_ttft_ms", "mean_tpot_ms", "median_tpot_ms", "p95_tpot_ms", "p99_tpot_ms",
           "mean_itl_ms", "p95_itl_ms", "p99_itl_ms", "p95_e2e_latency_ms")
FIELDS = ("max_concurrency", "random_input_len", "random_output_len", "random_range_ratio", "dataset_name")

def load(directory):
    rows = {}
    for concurrency in (1, 8, 32):
        path = Path(directory) / f"C{concurrency}.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if len(records) != 1:
            raise ValueError(f"{path.name}: expected one observation, got {len(records)}")
        row = records[0]
        expected = concurrency * 5
        if row.get("completed") != expected or row.get("max_concurrency") != concurrency:
            raise ValueError(f"C{concurrency}: incomplete requests or wrong concurrency")
        if row.get("random_input_len") != 16384 or row.get("random_output_len") != 2048:
            raise ValueError(f"C{concurrency}: input/output length changed")
        if row.get("total_input_tokens") != expected * 16384:
            raise ValueError(f"C{concurrency}: actual input token count differs from workload")
        if row.get("total_output_tokens", 0) <= 0:
            raise ValueError(f"C{concurrency}: no successful output tokens")
        for field in (*METRICS, "duration"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"C{concurrency}: invalid {field}")
        if row["duration"] <= 0 or row["output_throughput"] <= 0:
            raise ValueError(f"C{concurrency}: zero duration/throughput")
        rows[concurrency] = row
    return rows

def compare(baseline, candidate):
    results = []
    for concurrency in (1, 8, 32):
        old, new = baseline[concurrency], candidate[concurrency]
        if any(old.get(key) != new.get(key) for key in FIELDS):
            raise ValueError(f"C{concurrency}: workload conditions differ")
        results.append({"concurrency": concurrency, "requests": old["completed"],
                        "baseline_output_tokens": old["total_output_tokens"],
                        "candidate_output_tokens": new["total_output_tokens"],
                        "same_actual_output_tokens": old["total_output_tokens"] == new["total_output_tokens"],
                        "metrics": {key: {"baseline": old[key], "candidate": new[key],
                                          "change_pct": (new[key] / old[key] - 1) * 100 if old[key] else None}
                                    for key in METRICS}})
    return {"comparisons": results, "limitations": "One observation per concurrency. No statistical significance or per-layer attribution. Negative latency change is better; positive throughput change is better. Token differences and shared-host interference require explicit interpretation."}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path, nargs="?")
    args = parser.parse_args()
    baseline = load(args.baseline)
    result = compare(baseline, load(args.candidate)) if args.candidate else {
        "validated": True,
        "rows": {concurrency: {key: row[key] for key in (*METRICS, "duration", "completed", "total_input_tokens", "total_output_tokens")}
                 for concurrency, row in baseline.items()}}
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

```bash
docker exec -i h20_deepseek-v4-flash_sglang_pd-aggregation-client \
  python3 /client/compare_results.py /tmp/tuning-20261021-baseline-results /tmp/tuning-20261021-joint-v1-results
```

结果：205/205成功，三档实际输入输出token与基线相同。加载/验证/压测26分11秒，其中压测10分22秒。

| C | 输出tok/s：基线→联合 | 平均TTFT ms：基线→联合 | 平均TPOT ms：基线→联合 | P99 TPOT ms：基线→联合 |
|---:|---:|---:|---:|---:|
| 1 | 175.28→175.53 | 7323.16→7321.76 | 2.129→2.121 | 2.254→2.228 |
| 8 | 670.22→677.24 | 15837.10→16071.99 | 3.406→3.428 | 5.240→4.921 |
| 32 | 971.59→999.60 | 53333.84→51413.02 | 3.688→3.868 | 5.197→5.917 |

| C | 输出吞吐 | 平均TTFT | 平均TPOT | P99 TPOT |
|---:|---:|---:|---:|---:|
| 1 | +0.14% | −0.02% | −0.35% | −1.17% |
| 8 | +1.05% | +1.48% | +0.65% | −6.09% |
| 32 | +2.88% | −3.60% | +4.88% | +13.86% |

C32吞吐+2.88%，平均TPOT+4.88%、P99 TPOT+13.86%；未消融，单次测量含RDMA重试与共享负载。

