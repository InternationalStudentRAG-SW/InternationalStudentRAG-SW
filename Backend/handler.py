import time
import threading
import requests
import runpod
import uvicorn

def _start_server():
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="warning")

_thread = threading.Thread(target=_start_server, daemon=True)
_thread.start()

# FastAPI 서버가 뜰 때까지 대기
for _ in range(30):
    try:
        requests.get("http://localhost:8000/health", timeout=1)
        break
    except Exception:
        time.sleep(1)


def handler(job):
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
            timeout=120,
        )
        return {
            "status_code": response.status_code,
            "body": response.json(),
        }
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
