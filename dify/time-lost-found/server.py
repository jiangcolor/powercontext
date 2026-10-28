"""Trusted bridge between Dify and the official PowerContext HTTP server.

No model keys are handled here. SQLite stores rule state and idempotency receipts;
PowerContext stores and retrieves the narrative history sent to Dify.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from game import RuleError, advance

DATA = Path(os.environ.get("GAME_DATA_DIR", "var/game"))
DATA.mkdir(parents=True, exist_ok=True)
PC_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
PC_TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "")
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
BRIDGE_TOKEN_SHA256 = os.environ.get("BRIDGE_TOKEN_SHA256", "")
if BRIDGE_TOKEN_SHA256 and not re.fullmatch(r"[0-9a-f]{64}", BRIDGE_TOKEN_SHA256):
    raise RuntimeError("BRIDGE_TOKEN_SHA256 must be a lowercase SHA256 digest")
SALT_FILE = DATA / "scope-salt"
if not SALT_FILE.exists():
    fd = os.open(SALT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(secrets.token_hex(32))
SALT = SALT_FILE.read_text().strip().encode()
LOCK = threading.Lock()
app = FastAPI(
    title="时间回收站 · Dify × PowerContext", version="0.1.0",
    docs_url=None if os.environ.get("PUBLIC_BRIDGE") == "1" else "/docs",
    redoc_url=None if os.environ.get("PUBLIC_BRIDGE") == "1" else "/redoc",
    openapi_url=None if os.environ.get("PUBLIC_BRIDGE") == "1" else "/openapi.json",
)


def database():
    db = sqlite3.connect(DATA / "game.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, scope TEXT NOT NULL, state TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, player TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL)")
    return db


def pc(path: str, payload: dict):
    headers = {"Content-Type": "application/json"}
    if PC_TOKEN:
        headers["Authorization"] = f"Bearer {PC_TOKEN}"
    request = Request(PC_URL + path, json.dumps(payload, ensure_ascii=False).encode(), headers)
    try:
        with urlopen(request, timeout=25) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        # Never echo upstream URLs, headers or payloads in client-facing errors.
        raise HTTPException(503, "记忆柜暂时打不开，请稍后重试；本次不会跳过记忆步骤。") from error


class Turn(BaseModel):
    player_code: str = Field(min_length=12, max_length=80)
    request_id: str = Field(min_length=8, max_length=100)
    action: str
    offering: str = Field(default="", max_length=200)


@app.get("/health")
def health():
    return {"status": "ok", "service": "time-lost-found", "version": "0.1.0"}


@app.post("/turn")
def turn(body: Turn, authorization: str | None = Header(default=None)):
    if BRIDGE_TOKEN_SHA256:
        supplied = (authorization or "").removeprefix("Bearer ")
        if not (authorization or "").startswith("Bearer ") or not secrets.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), BRIDGE_TOKEN_SHA256):
            raise HTTPException(401, "需要有效的作品服务凭据。")
    elif BRIDGE_TOKEN and not secrets.compare_digest(authorization or "", "Bearer " + BRIDGE_TOKEN):
        raise HTTPException(401, "需要有效的作品服务凭据。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", body.player_code):
        raise HTTPException(422, "玩家卡请使用至少 12 位英文字母、数字、下划线或横线。")
    player = hmac.new(SALT, body.player_code.encode(), hashlib.sha256).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    with LOCK, database() as db:
        old = db.execute("SELECT player, fingerprint, response FROM receipts WHERE id=?", (body.request_id,)).fetchone()
        if old:
            if old[:2] != (player, fingerprint):
                raise HTTPException(409, "请求编号已被使用，请发起一次新操作。")
            return json.loads(old[2])
        row = db.execute("SELECT scope, state FROM players WHERE id=?", (player,)).fetchone()
        state = json.loads(row[1]) if row and row[1] else None
        try:
            new_state, scene = advance(state, body.action, body.offering)
        except RuleError as error:
            raise HTTPException(422, str(error)) from error
        if row:
            scope = row[0]
        else:
            scope = pc("/v1/scopes", {"title": "时间回收站", "summary": "Fictional player story history", "idempotency_key": "tlf-" + player})["scope_id"]
        prepared = pc("/v1/context/prepare", {"scope_id": scope, "query": "time_lost_found story memory", "max_bytes": 12000})
        history = prepared.get("content") or ""
        if state and not history:
            raise HTTPException(503, "没有找到上次的记忆，暂时不能继续；请检查 PowerContext 检索配置。")
        event = "time_lost_found story memory\n" + json.dumps({"action": body.action, "offering": body.offering, "state": new_state}, ensure_ascii=False)
        remembered = pc("/v1/memory/remember", {"scope_id": scope, "kind": "decision", "text": event, "reason": "玩家主动选择保存的虚构故事进展"})
        records = remembered.get("records") or []
        if not records:
            raise HTTPException(503, "记忆未保存成功，暂时不能继续。")
        result = {
            "state": new_state,
            "scene": scene,
            "memory_status": prepared.get("status"),
            "memory_context": history,
            "memory_records": records,
            "scope_id": scope,
            "receipt": body.request_id,
            "note": "玩家选择已保存；叙事由 Dify 模型节点生成。",
        }
        db.execute("INSERT INTO players VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state", (player, scope, json.dumps(new_state, ensure_ascii=False)))
        db.execute("INSERT INTO receipts VALUES(?,?,?,?)", (body.request_id, player, fingerprint, json.dumps(result, ensure_ascii=False)))
        return result
