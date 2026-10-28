"""Static DSL checks and execution of Code nodes; NOT a Dify import test."""
from pathlib import Path
import json
import yaml

root = Path(__file__).resolve().parents[1]
dsl = yaml.safe_load((root / "time-lost-found.yml").read_text())
nodes = {node["id"]: node["data"] for node in dsl["workflow"]["graph"]["nodes"]}
assert dsl["kind"] == "app" and dsl["app"]["mode"] == "workflow"
assert len(nodes) == 7
assert {n["type"] for n in nodes.values()} >= {"start", "code", "http-request", "llm", "template-transform", "end"}
assert nodes["narrator"]["model"]["provider"] == "langgenius/tongyi/tongyi"
assert nodes["narrator"]["model"]["name"] == "qwen-plus"
assert dsl["version"] == "0.7.0"
serialize = {}
exec(nodes["serialize"]["code"], serialize)
payload = serialize["main"]("test_card_12345", "寄存", '带引号"和\\反斜线\n的物品')["payload"]
assert json.loads(payload)["offering"] == '带引号"和\\反斜线\n的物品'
parse = {}
exec(nodes["parse"]["code"], parse)
try:
    parse["main"]('{"detail":"记忆柜暂时打不开"}', 503)
except ValueError as error:
    assert "记忆柜" in str(error)
else:
    raise AssertionError("Upstream failure must stop narration")
print("PASS static graph + JSON escaping + failure stops narration; this script does not verify Dify import/runtime")
