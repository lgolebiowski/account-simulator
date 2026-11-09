"""Shared helpers for the hook scripts (standard library only)."""
import fnmatch
import json
import subprocess
import sys
import tempfile
from pathlib import Path

OWNERSHIP = Path(__file__).resolve().parent.parent / "ownership.json"


def load_ownership() -> dict:
    return json.loads(OWNERSHIP.read_text())


def repo_root(cwd: str) -> Path:
    """The git top-level of `cwd` (so a worktree is its own root), else the script's repo."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
        return Path(out).resolve()
    except (subprocess.SubprocessError, OSError):
        return OWNERSHIP.parent.parent


def relative_to_root(path: str, cwd: str, root: Path) -> str | None:
    """Repo-relative posix path, or None when the file is outside the repo."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd) / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def in_temp_dir(path: str) -> bool:
    resolved = str(Path(path).resolve())
    return any(resolved.startswith(prefix) for prefix in
               {str(Path(tempfile.gettempdir()).resolve()), "/tmp", "/private/tmp"})


def matches(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def check_owned(rel: str, agent: str, rules: dict) -> str | None:
    """None if `agent` may edit `rel`, else the reason it may not."""
    if agent not in rules["agents"]:
        return f"no ownership rules for agent '{agent}' in .claude/ownership.json"
    mine = rules["agents"][agent]
    if matches(rel, rules["global_deny"]):
        return f"{rel} is orchestrator-owned (CLAUDE.md, .claude/, docs/, requirements, config)"
    if matches(rel, mine["deny"]):
        return f"{rel} belongs to another agent"
    if not matches(rel, mine["allow"]):
        owned = ", ".join(mine["allow"]) or "nothing (read-only agent)"
        return f"{rel} is not owned by {agent}. It may edit: {owned}"
    return None


def read_hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
