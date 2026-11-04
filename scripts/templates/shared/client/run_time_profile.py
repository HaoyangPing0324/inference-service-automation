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
