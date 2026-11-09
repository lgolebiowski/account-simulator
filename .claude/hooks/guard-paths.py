#!/usr/bin/env python3
"""PreToolUse hook for subagents: block Edit/Write outside the agent's owned files.

Usage in an agent's frontmatter: guard-paths.py --agent backend-engineer
Exit 0 = allowed. Exit 2 = blocked (stderr is the reason shown to the agent). Fails closed.
Limit: this covers the Edit/Write tools only, not shell redirects. The orchestrator runs
audit-ownership.py after each agent as the second line of defence.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--agent":
        print("guard-paths: usage: guard-paths.py --agent NAME", file=sys.stderr)
        return 2
    agent = sys.argv[2]
    data = c.read_hook_input()
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        print("guard-paths: could not read the target file path; blocking to be safe.", file=sys.stderr)
        return 2
    cwd = data.get("cwd") or os.getcwd()
    rel = c.relative_to_root(path, cwd, c.repo_root(cwd))
    if rel is None:
        if c.in_temp_dir(path):
            return 0  # scratch files in the OS temp dir are fine
        print(f"BLOCKED: {path} is outside the project. Report what you need to the orchestrator.",
              file=sys.stderr)
        return 2
    try:
        reason = c.check_owned(rel, agent, c.load_ownership())
    except (OSError, ValueError, KeyError) as e:
        print(f"guard-paths: cannot read ownership rules ({e}); blocking to be safe.", file=sys.stderr)
        return 2
    if reason:
        print(f"BLOCKED by file ownership: {reason}. Do not work around it (no shell edits); "
              "describe the change you need in your report so the orchestrator can route it.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
