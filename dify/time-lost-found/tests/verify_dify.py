"""Run three independent REAL Dify Workflow API calls, once configured.

API keys stay in process environment and are never written to evidence.
"""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
import uuid

key = os.environ.get("DIFY_APP_API_KEY")
if not key:
    raise SystemExit("尚未配置 DIFY_APP_API_KEY；没有执行 Dify 测试，不能标记通过。")
url = os.environ.get("DIFY_API_URL", "https://api.dify.ai/v1").rstrip("/")
player = "dify-review-" + uuid.uuid4().hex[:20]
results = {"test_type": "Real Dify Workflow API; independent calls sharing only player card", "runs": []}
for action, offering in [("寄存", "一只只在周一响的闹钟"), ("改写", "朋友。我想让它有个愿意等它的人。"), ("重逢", "")]:
    payload = {"inputs": {"player_code": player, "action": action, "offering": offering}, "response_mode": "blocking", "user": "competition-review"}
    request = Request(url + "/workflows/run", json.dumps(payload).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urlopen(request, timeout=180) as response:
        result = json.load(response)
    data = result.get("data", {})
    assert data.get("status") == "succeeded", "Dify 运行失败，请在工作区检查节点；本工具不会输出可能含配置的原始错误。"
    outputs = data.get("outputs", {})
    assert outputs.get("story") and outputs.get("memory_receipt")
    results["runs"].append({"action": action, "offering": offering, "workflow_run_id": result.get("workflow_run_id"), "status": data["status"], "outputs": outputs})
    print("PASS Dify", action, "run", result.get("workflow_run_id"))
target = Path("evidence/live-dify.json")
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("请人工核对三幕叙事是否正确呼应物品与选择；API成功不等于趣味和记忆表现已通过人工验收。")
