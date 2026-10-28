"""Exercise the REAL bridge and PowerContext. This does not execute Dify."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid

URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
TOKEN = os.environ.get("BRIDGE_TOKEN", "")
RUN = uuid.uuid4().hex[:12]
evidence = {"run": RUN, "test_type": "Real HTTP bridge + official PowerContext; Dify/model NOT executed", "steps": [], "checks": []}


def post(payload, expected=200):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    try:
        with urlopen(Request(URL + "/turn", json.dumps(payload).encode(), headers), timeout=120) as response:
            code, data = response.status, json.load(response)
    except HTTPError as error:
        code, data = error.code, json.loads(error.read())
    assert code == expected, (code, data)
    evidence["steps"].append({"input": payload, "status": code, "response": data})
    return data


def turn(player, action, offering="", expected=200, request_id=None):
    return post({"player_code": player, "action": action, "offering": offering, "request_id": request_id or str(uuid.uuid4())}, expected)


for branch, badge in [("自由", "放手收藏家"), ("打工", "时间资本家"), ("朋友", "异物知己")]:
    player = "review-" + RUN + "-" + str(len(evidence["checks"]))
    first = turn(player, "寄存", "一只只在周一响的闹钟")
    assert first["memory_status"] == "empty"
    assert first["memory_records"] and first["state"]["chapter"] == 1
    second = turn(player, "改写", "我选择" + branch + "，因为时间也值得有自己的生活。")
    assert second["memory_status"] == "ready"
    assert "一只只在周一响的闹钟" in second["memory_context"]
    third = turn(player, "重逢")
    assert third["state"]["ending"] == badge
    assert branch in third["memory_context"]
    assert first["scope_id"] == third["scope_id"]
    evidence["checks"].append("PASS real memory recall + ending " + badge)

# Stable replay must not advance a chapter or create new Artifact records.
player = "replay-" + RUN
request_id = str(uuid.uuid4())
first = turn(player, "寄存", '会说“hello”的月亮\\碎片', request_id=request_id)
replay = turn(player, "寄存", '会说“hello”的月亮\\碎片', request_id=request_id)
assert first == replay
turn(player, "寄存", "偷偷替换的物品", expected=409, request_id=request_id)
evidence["checks"].append("PASS identical retry is idempotent; conflicting request_id rejected")

# Different player scopes cannot retrieve one another's fictional story.
other = turn("isolated-" + RUN, "寄存", "不会醒的枕头")
assert other["scope_id"] != first["scope_id"]
assert other["memory_status"] == "empty" and not other["memory_context"]
turn("empty-" + RUN, "重逢", expected=422)
turn(player, "改写", "自由和朋友", expected=422)
turn(player, "寄存", "重复寄存", expected=422)
turn("short", "寄存", "物品", expected=422)
evidence["checks"].append("PASS player isolation, ordering, ambiguous choice, duplicate deposit, invalid card")

target = Path(os.environ.get("EVIDENCE_FILE", "evidence/live-backend.json"))
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
for check in evidence["checks"]:
    print(check)
print("Actual HTTP steps:", len(evidence["steps"]), "Evidence:", target)
