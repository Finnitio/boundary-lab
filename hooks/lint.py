"""PostToolUse: ruff check --fix the edited Python file and report leftovers to the agent."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if not path.endswith(".py") or not Path(path).is_file():
        return
    venv = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python = str(venv) if venv.exists() else sys.executable
    cmd = [python, "-m", "ruff", "check", "--fix", "--force-exclude", "--quiet", path]
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return
    if "No module named ruff" in result.stderr:
        return
    if result.returncode:
        print(f"ruff found issues in {path}:\n{result.stdout}{result.stderr}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
