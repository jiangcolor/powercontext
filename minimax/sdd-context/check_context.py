"""Real seekdb and PowerContext verification; no simulated MiniMax calls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    evidence = ROOT / "evidence" / "offline"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sdd-clean-") as temporary:
        run = Path(temporary)
        project = run / "demo"
        shutil.copytree(ROOT / "demo", project)
        state = run / "state"
        steps = []

        def invoke(command, *args):
            cli = [sys.executable, "-m", "sdd_context", command, "--project", str(project),
                   "--state", str(state), "--evidence", str(evidence), *args]
            result = subprocess.run(cli, cwd=ROOT, text=True, capture_output=True)
            if result.returncode:
                (evidence / "failure.log").write_text(result.stdout + result.stderr)
                raise RuntimeError(f"{command} failed; see evidence/offline/failure.log")
            data = json.loads(result.stdout)
            steps.append({"command": cli, "exit_code": result.returncode, "stderr": result.stderr, "result": data})
            return data

        empty = invoke("resume")
        assert empty["states"] == [] and empty["latest"] is None
        imported = invoke("ingest")
        assert "seekdb" in imported["database"]
        first = invoke("context")
        assert {s["kind"] for s in first["retrieval"]["sources"]} == {"spec", "code", "test"}
        assert first["task_state"]["latest"] is None
        recorded = invoke("record", "--done", "baseline verified", "--todo", "MiniMax code generation",
                          "--validation", "target fails; regressions pass")
        recalled = invoke("resume")
        assert recorded["pid"] != recalled["pid"]
        assert recalled["latest"]["done"] == "baseline verified" and recalled["citations"]
        resumed = invoke("context")
        assert resumed["task_state"]["latest"]["todo"] == "MiniMax code generation"
        path = project / "specs" / "tickets.md"
        revised = path.read_text().replace("version 1", "version 2") + "\nSPEC-REVISION: ticket status filter rollout reviewed at revision 2.\n"
        path.write_text(revised)
        invoke("ingest")
        updated = invoke("context")
        source = next(s for s in updated["retrieval"]["sources"] if s["kind"] == "spec")
        assert "version 2" in source["body"] and "version 1" not in source["body"]
        assert source["sha256"] == hashlib.sha256(revised.encode()).hexdigest()
        before = invoke("verify", "--phase", "before")
        assert before["results"]["TargetStatusTests"]["exit_code"] == 1
        assert before["results"]["RegressionTests"]["exit_code"] == 0
        report = {"result": "passed", "database": imported["database"], "checks": [
            "real seekdb sources and FTS context", "PowerContext starts empty", "state survives process restart",
            "saved state used by subsequent context", "reimport replaces old specification", "baseline behavior verified",
        ], "MiniMax": "pending actual provider invocation", "steps": steps}
        (ROOT / "evidence" / "offline-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "steps"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
