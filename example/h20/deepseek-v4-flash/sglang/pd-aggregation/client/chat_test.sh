#!/usr/bin/env bash
set -euo pipefail

CONFIG=${EXPERIMENT_ENV:-/experiment.env}
# shellcheck source=/dev/null
source "$CONFIG"

ENCODER="$MODEL_PATH/encoding/encoding_dsv4.py"
[[ -f "$ENCODER" ]] || { echo "Official model encoder not found: $ENCODER" >&2; exit 2; }

python3 - "$SERVICE_PORT" "$SERVED_MODEL_NAME" "$ENCODER" <<'PY'
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
PY
