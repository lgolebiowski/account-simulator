#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write): fast checks on the file that was just written.

  .py  -> must compile; no `float` in money code (bankapp/, cli.py); ruff (if installed)
  .js  -> node --check
  .json-> must parse
Exit 0 = fine. Exit 2 = problem; stderr is shown to Claude so it fixes it right away.
The edit has already happened, so this is feedback, not a rollback. Slow checks (the full
test suite) are deliberately not here: run /run-regression for those.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402

MONEY_PATHS = ("bankapp/", "cli.py")


def float_uses(source: str) -> list[int]:
    """Line numbers where the name `float`/`Float` appears as code (not in strings or comments)."""
    lines = source.splitlines()
    hits = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NAME and tok.string in ("float", "Float"):
                if "allow-float" not in lines[tok.start[0] - 1]:
                    hits.append(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass  # a syntax problem is reported by the compile check
    return hits


def find_tool(root: Path, name: str) -> str | None:
    for base in (root, c.OWNERSHIP.parent.parent):
        candidate = base / ".venv" / "bin" / name
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def run(cmd, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=25)


def main() -> int:
    data = c.read_hook_input()
    path = (data.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    root = c.repo_root(cwd)
    rel = c.relative_to_root(path, cwd, root)
    target = Path(path) if Path(path).is_absolute() else Path(cwd) / path
    if rel is None or not target.is_file() or rel.startswith((".venv/", ".claude/worktrees/")):
        return 0

    problems = []
    try:
        if rel.endswith(".py"):
            source = target.read_text()
            try:
                compile(source, rel, "exec")
            except SyntaxError as e:
                problems.append(f"{rel}:{e.lineno}: syntax error: {e.msg}")
            else:
                if rel.startswith(MONEY_PATHS):
                    for line in float_uses(source):
                        problems.append(
                            f"{rel}:{line}: `float` in money code. Use Decimal "
                            "(.claude/rules/money.md). Mark a genuine non-money use with `# allow-float`.")
                ruff = find_tool(root, "ruff")
                if ruff:
                    r = run([ruff, "check", "--quiet", "--no-cache", rel], root)
                    if r.returncode != 0:
                        problems.append(f"ruff found problems in {rel}:\n{(r.stdout or r.stderr).strip()}")
        elif rel.endswith(".js"):
            node = shutil.which("node")
            if node:
                r = run([node, "--check", rel], root)
                if r.returncode != 0:
                    problems.append(f"{rel} failed `node --check`:\n{r.stderr.strip()}")
        elif rel.endswith(".json"):
            try:
                json.loads(target.read_text())
            except ValueError as e:
                problems.append(f"{rel} is not valid JSON: {e}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"post-edit-check: skipped ({e})", file=sys.stderr)
        return 0

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
