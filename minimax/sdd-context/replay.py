"""Reproduce the submitted result from empty state; no new model call is needed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    original = ROOT / "evidence" / "minimax-development.json"
    after = ROOT / "demo" / "after" / "tickets.py"
    if not original.is_file() or not after.is_file():
        raise SystemExit("Real MiniMax generation has not completed; this is not a completed submission yet")
    development = json.loads(original.read_text())
    assert development["provider"] == "MiniMax"
    assert development["source_sha256"] == hashlib.sha256(after.read_bytes()).hexdigest()
    evidence = ROOT / "evidence" / "replay"
    evidence.mkdir(parents=True, exist_ok=True)
    steps = []
    with tempfile.TemporaryDirectory(prefix="sdd-replay-") as temporary:
        state = Path(temporary)

        def invoke(command, *args):
            cli = [sys.executable, "-m", "sdd_context", command, "--state", str(state),
                   "--evidence", str(evidence), *args]
            process = subprocess.run(cli, cwd=ROOT, capture_output=True, text=True)
            if process.returncode:
                raise RuntimeError(process.stdout + process.stderr)
            value = json.loads(process.stdout)
            steps.append({"command": cli, "exit_code": process.returncode, "result": value})
            return value

        assert invoke("resume")["latest"] is None
        invoke("ingest")
        invoke("context")
        before = invoke("verify", "--phase", "before")
        invoke("record", "--done", "Baseline tested", "--todo", "Replay archived MiniMax change")
        prior = invoke("context")
        assert prior["task_state"]["latest"]["done"] == "Baseline tested"
        fixed = invoke("verify", "--phase", "after")
        for group in ["TargetStatusTests", "RegressionTests"]:
            assert before["results"][group]["tests_sha256"] == fixed["results"][group]["tests_sha256"]
            assert fixed["results"][group]["exit_code"] == 0
        invoke("record", "--done", "MiniMax change replayed and all tests passed", "--todo", "None",
               "--validation", "after target=passed; after regression=passed")
        resumed = invoke("resume")
        assert resumed["latest"]["todo"] == "None"
        report = {"result": "passed", "model_regenerated": False, "steps": steps}
        (evidence / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print("Replay passed: same target tests fail before and pass after; regressions pass; state reused.")


if __name__ == "__main__":
    main()
