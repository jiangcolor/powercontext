"""Real bridge process restart, authentication, and unavailable-upstream test."""
import json
import hashlib
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import uuid

ROOT = Path(__file__).resolve().parents[1]
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
token = secrets.token_hex(32)
base = f"http://127.0.0.1:{port}"
player = "resilience-" + uuid.uuid4().hex[:20]
evidence = {"test_type": "Real bridge processes and official PowerContext; Dify NOT executed", "checks": [], "steps": []}


def post(action, offering="", auth=True, expected=200):
    payload = {"player_code": player, "request_id": str(uuid.uuid4()), "action": action, "offering": offering}
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(base + "/turn", json.dumps(payload).encode(), headers), timeout=30) as response:
            status, data = response.status, json.load(response)
    except HTTPError as error:
        status, data = error.code, json.loads(error.read())
    assert status == expected, (status, data)
    evidence["steps"].append({"action": action, "authenticated": auth, "status": status, "response": data})
    return data


with tempfile.TemporaryDirectory(prefix="tlf-resilience-") as directory:
    env = dict(os.environ, GAME_DATA_DIR=directory, BRIDGE_TOKEN_SHA256=hashlib.sha256(token.encode()).hexdigest(), PUBLIC_BRIDGE="1")
    log = open(Path(directory) / "bridge.log", "w")

    def start(upstream):
        env["POWERCONTEXT_URL"] = upstream
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--app-dir", str(ROOT), "--host", "127.0.0.1", "--port", str(port), "--workers", "1"], env=env, stdout=log, stderr=log)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Bridge test process exited")
            try:
                with urlopen(base + "/health", timeout=0.2):
                    return process
            except (URLError, TimeoutError):
                time.sleep(0.1)
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError("Bridge startup timed out")

    upstream = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8900")
    process = start(upstream)
    try:
        post("寄存", "拒绝失忆的纸飞机", auth=False, expected=401)
        first = post("寄存", "拒绝失忆的纸飞机")
        evidence["checks"].append("PASS unauthenticated request rejected, valid request writes memory")
    finally:
        process.terminate()
        process.wait(timeout=10)
    # An unbound localhost port exercises a real failed upstream connection.
    process = start("http://127.0.0.1:9")
    try:
        post("改写", "朋友", expected=503)
        evidence["checks"].append("PASS unavailable PowerContext fails closed")
    finally:
        process.terminate()
        process.wait(timeout=10)
    process = start(upstream)
    try:
        second = post("改写", "朋友")
        assert second["state"]["chapter"] == 2
        assert second["scope_id"] == first["scope_id"]
        assert "拒绝失忆的纸飞机" in second["memory_context"]
        evidence["checks"].append("PASS restart preserves binding and history; failed request did not advance state")
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()
target = Path(os.environ.get("RESILIENCE_EVIDENCE", "evidence/resilience.json"))
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
for item in evidence["checks"]:
    print(item)
