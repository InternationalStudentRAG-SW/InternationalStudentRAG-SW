import time
import threading
import requests
import runpod
import uvicorn
import traceback

_server_ready = False
_server_error = None


def _start_server():
    global _server_error
    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
    except Exception:
        _server_error = traceback.format_exc()
        print(f"[handler] FastAPI crashed:\n{_server_error}", flush=True)


_thread = threading.Thread(target=_start_server, daemon=True)
_thread.start()

for i in range(60):
    if _server_error:
        print(f"[handler] FastAPI failed to start after {i}s", flush=True)
        break
    try:
        r = requests.get("http://localhost:8000/health", timeout=1)
        if r.status_code == 200:
            _server_ready = True
            print(f"[handler] FastAPI ready ({i+1}s)", flush=True)
            break
    except Exception:
        pass
    time.sleep(1)

if not _server_ready:
    print(f"[handler] FastAPI not ready. error={_server_error}", flush=True)


def handler(job):
    if not _server_ready:
        return {"error": f"FastAPI not started. reason={_server_error or 'timeout after 60s'}"}

    job_input = job.get("input", {})
    path = job_input.get("path", "/health")
    method = job_input.get("method", "GET").upper()
    body = job_input.get("body", None)
    headers = job_input.get("headers", {})

    try:
        response = requests.request(
            method,
            f"http://localhost:8000{path}",
            json=body,
            headers=headers,
            timeout=300,
        )
        return {
            "status_code": response.status_code,
            "body": response.json(),
        }
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
