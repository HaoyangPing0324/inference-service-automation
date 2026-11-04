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
