#!/usr/bin/env python3
"""After an agent returns: list changed files that agent does not own.

Usage: audit-ownership.py --agent NAME [--base REF]    (run from the repo or worktree root)
Compares the working tree and commits since REF (default HEAD) with .claude/ownership.json.
Exit 0 = all changes owned. Exit 1 = violations (listed). Catches shell-based edits that the
Edit/Write guard cannot see.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as c  # noqa: E402


def git(root, *args) -> list[str]:
    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--base", default="HEAD")
    args = ap.parse_args()
    root = c.repo_root(os.getcwd())
    changed = set(git(root, "diff", "--name-only", args.base))           # committed + unstaged vs base
    changed |= set(git(root, "diff", "--name-only", "--cached"))
    changed |= set(git(root, "ls-files", "--others", "--exclude-standard"))  # new files
    rules = c.load_ownership()
    bad = {}
    for rel in sorted(changed):
        reason = c.check_owned(rel, args.agent, rules)
        if reason:
            bad[rel] = reason
    print(f"{args.agent}: {len(changed)} changed file(s) since {args.base}")
    for rel in sorted(changed):
        print(f"  {'VIOLATION' if rel in bad else 'ok       '} {rel}")
    for reason in bad.values():
        print(f"  -> {reason}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
