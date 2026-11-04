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
