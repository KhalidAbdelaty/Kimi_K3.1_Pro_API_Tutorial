"""Run model-written CadQuery code in an isolated container and render the result.

The container gets the candidate file and a scratch folder. It gets no network,
no API key, no reference geometry, and hard limits on memory, CPU, processes,
and time.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import cadquery as cq

from cadkit.render import render_all

IMAGE = "cad-sandbox:2.8.0"
TIMEOUT_S = 60
MAX_CODE_CHARS = 20_000
ENTRY = Path(__file__).resolve().parent.parent / "sandbox" / "entry.py"


def _docker_cmd(work: Path, name: str) -> list[str]:
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",              # no outbound access
        "--read-only",                    # immutable root filesystem
        "--tmpfs", "/tmp:size=64m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "1g", "--cpus", "1", "--pids-limit", "128",
        "-e", "HOME=/tmp", "-e", "MPLCONFIGDIR=/tmp",
        "-v", f"{work}:/work",            # the only writable mount
        IMAGE,
    ]


def execute(code: str, work: Path) -> dict:
    """Execute one candidate program. Returns the sandbox report plus timing."""
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if len(code) > MAX_CODE_CHARS:
        return {"ok": False, "error_type": "CodeTooLong",
                "error": f"program exceeds {MAX_CODE_CHARS} characters"}
    (work / "candidate.py").write_text(code, encoding="utf-8")
    if os.name == "posix":
        os.chmod(work, 0o777)  # the container runs as an unprivileged user

    mode = os.environ.get("CAD_SANDBOX", "docker")
    name = f"cad-{uuid.uuid4().hex[:8]}"
    if mode == "docker":
        cmd = _docker_cmd(work, name)
        env = None
    else:  # local debugging only: a clean env, but not isolation
        print("WARNING: CAD_SANDBOX=subprocess runs model code on this machine.", file=sys.stderr)
        cmd = [sys.executable, str(ENTRY)]
        env = {"PATH": os.environ.get("PATH", ""), "CAD_WORK": str(work),
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}

    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, env=env)
        stderr_tail = proc.stderr[-600:]
    except subprocess.TimeoutExpired:
        if mode == "docker":
            subprocess.run(["docker", "kill", name], capture_output=True)
        return {"ok": False, "error_type": "Timeout",
                "error": f"execution exceeded {TIMEOUT_S} s", "seconds": TIMEOUT_S}
    seconds = round(time.perf_counter() - start, 2)

    report_path = work / "report.json"
    if not report_path.exists():
        return {"ok": False, "error_type": "SandboxError",
                "error": stderr_tail or "no report written", "seconds": seconds}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["seconds"] = seconds
    return report


def render(work: Path) -> list[Path]:
    """Render the candidate STEP from the four fixed reference cameras."""
    shape = cq.importers.importStep(str(Path(work) / "candidate.step")).val()
    return render_all(shape, Path(work) / "views")


if __name__ == "__main__":
    # Smoke test: python -m cadkit.runner path/to/program.py
    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = Path("runs") / "smoke"
    shutil.rmtree(out, ignore_errors=True)
    print(json.dumps(execute(src, out), indent=2))
