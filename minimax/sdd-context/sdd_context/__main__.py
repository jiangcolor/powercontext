"""CLI: ingest, context, record, resume, develop, verify."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen

from .index import ingest, retrieve

ROOT = Path(__file__).resolve().parent.parent
TASK = "Implement ticket status filter; preserve newest first order, limit and input nonmutation compatibility."


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def state_operation(directory: Path, state=None) -> dict:
    result = subprocess.run([sys.executable, "-m", "sdd_context.state"],
                            input=json.dumps({"directory": str(directory.resolve()), "state": state}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def context(args) -> dict:
    recalled = retrieve(args.state / "seekdb", args.task)
    prior = state_operation(args.state / "powercontext")
    value = {"task": args.task, "retrieval": recalled, "task_state": prior}
    if {source["kind"] for source in recalled["sources"]} != {"spec", "code", "test"}:
        raise ValueError("Context is missing applicable specification, code or tests; refine the task")
    write_json(args.evidence / "context.json", value)
    return value


def code_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(args, phase: str) -> dict:
    source = args.project / phase / "tickets.py"
    if not source.is_file():
        raise ValueError(f"Missing {phase} snapshot; MiniMax must generate the after snapshot first")
    test_path = args.project / "tests" / "test_tickets.py"
    results = {}
    for group in ["TargetStatusTests", "RegressionTests"]:
        command = [sys.executable, str(test_path), "-v", group]
        proc = subprocess.run(command, env={**os.environ, "TICKETS_SOURCE": str(source.resolve())},
                              text=True, capture_output=True)
        results[group] = {"command": command, "exit_code": proc.returncode,
                          "stdout": proc.stdout, "stderr": proc.stderr,
                          "source_sha256": code_hash(source), "tests_sha256": code_hash(test_path)}
    value = {"phase": phase, "code_version_sha256": code_hash(source), "results": results}
    write_json(args.evidence / f"tests-{phase}.json", value)
    return value


def develop(args) -> dict:
    bundle = context(args)
    prompt = (
        "You are an AI coding assistant using specification-driven development. "
        "Implement the task using the provided CURRENT source records and prior task state. "
        "Modify only the list_tickets function. Preserve its signature, all compatibility rules and test assertions. "
        "Return only the COMPLETE replacement tickets.py in a python code fence, no reasoning. "
        "Do not import modules or add other functions/classes.\n" + json.dumps(bundle, ensure_ascii=False)
    )
    key_path = ROOT / ".secrets" / "minimax-key"
    key = os.environ.get("MINIMAX_API_KEY") or (key_path.read_text().strip() if key_path.is_file() else "")
    if not key:
        raise ValueError("Configure MINIMAX_API_KEY or .secrets/minimax-key locally; never commit credentials")
    endpoint = os.environ.get("MINIMAX_ENDPOINT", "https://api.minimaxi.com/v1/chat/completions")
    if endpoint not in {"https://api.minimaxi.com/v1/chat/completions", "https://api.minimax.io/v1/chat/completions"}:
        raise ValueError("Only official MiniMax endpoints are accepted")
    payload = {"model": os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7"),
               "messages": [{"role": "user", "content": prompt}], "temperature": 1.0,
               "max_tokens": 4096, "stream": False}
    request = Request(endpoint, data=json.dumps(payload).encode(),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    # Record the request context before calling; credentials are deliberately excluded.
    write_json(args.evidence / "minimax-request.json", {"endpoint": endpoint, "request": payload})
    with urlopen(request, timeout=180) as response:
        reply = json.load(response)
    content = reply["choices"][0]["message"]["content"]
    # Model private reasoning is not evidence and is never saved.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    fence = re.search(r"```(?:python)?\s*\n(.*?)```", content, re.S)
    code = (fence.group(1) if fence else content).strip() + "\n"
    tree = ast.parse(code)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "list_tickets":
        raise ValueError("MiniMax response must define only list_tickets")
    if any(not isinstance(node, (ast.FunctionDef, ast.Expr)) for node in tree.body):
        raise ValueError("MiniMax response includes unexpected top-level statements")
    forbidden = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)
    if any(isinstance(node, forbidden) or (isinstance(node, ast.Attribute) and node.attr.startswith("_"))
           for node in ast.walk(tree)):
        raise ValueError("Generated code contains unsupported operations; inspect the response before using it")
    allowed_calls = {"sorted", "ValueError", "type", "isinstance", "int", "len", "list", "set"}
    if any(isinstance(node, ast.Call) and
           (not isinstance(node.func, ast.Name) or node.func.id not in allowed_calls) for node in ast.walk(tree)):
        raise ValueError("Generated code calls an unexpected function")
    before = (args.project / "before" / "tickets.py").read_text()
    path = args.project / "after" / "tickets.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    patch = "".join(difflib.unified_diff(before.splitlines(True), code.splitlines(True),
                                     fromfile="demo/before/tickets.py", tofile="demo/after/tickets.py"))
    (args.evidence / "code.patch").write_text(patch, encoding="utf-8")
    value = {"provider": "MiniMax", "model": reply.get("model", payload["model"]),
             "response_id": reply.get("id"), "usage": reply.get("usage"), "content": content,
             "source_sha256": code_hash(path), "context_sha256": code_hash(args.evidence / "context.json")}
    write_json(args.evidence / "minimax-development.json", value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "context", "record", "resume", "develop", "verify"])
    parser.add_argument("--project", type=Path, default=ROOT / "demo")
    parser.add_argument("--state", type=Path, default=ROOT / ".state")
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence")
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--phase", choices=["before", "after"], default="before")
    parser.add_argument("--done", default="")
    parser.add_argument("--todo", default="")
    parser.add_argument("--validation", default="not-run")
    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest(args.project, args.state / "seekdb")
    elif args.command == "context":
        result = context(args)
    elif args.command == "resume":
        result = state_operation(args.state / "powercontext")
    elif args.command == "record":
        result = state_operation(args.state / "powercontext", {
            "task": args.task, "done": args.done, "todo": args.todo, "validation": args.validation,
        })
    elif args.command == "develop":
        result = develop(args)
    else:
        result = run_tests(args, args.phase)
    args.evidence.mkdir(parents=True, exist_ok=True)
    with (args.evidence / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "command": args.command,
                                 "pid": os.getpid(), "result": result}, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "verify":
        expected = args.phase == "after"
        target_ok = result["results"]["TargetStatusTests"]["exit_code"] == 0
        regression_ok = result["results"]["RegressionTests"]["exit_code"] == 0
        if target_ok != expected or not regression_ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
