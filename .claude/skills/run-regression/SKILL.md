---
name: run-regression
description: "Run the full pytest regression suite plus the static checks (ruff, bandit, pip-audit) and report the exact results honestly, without fixing anything. Use before and after changes, or whenever the user asks whether everything still passes."
argument-hint: "[optional pytest arguments]"
context: fork
agent: qa-engineer
background: false
allowed-tools: Bash(.claude/bin/test.sh*) Bash(.claude/bin/audit.sh*) Bash(git status*) Bash(git log*) Bash(docker compose ps*)
---

# Regression run

Run these from the repo (or worktree) root and report **exactly what you saw**. Do not edit any file and do not try to fix failures.

1. `git log --oneline -1` and `git status --short`: report the commit and whether the tree is clean.
2. `.claude/bin/test.sh $ARGUMENTS`
   - If it prints that Postgres is not reachable, report **"NOT RUN: database is down"** and stop. That is not a pass. (Start it with `docker compose up -d --wait`.)
   - Otherwise report the verbatim pytest summary line (`N passed, M failed ...`).
3. `.claude/bin/audit.sh` and report ruff, bandit and pip-audit results separately.

For every failure give: the test id, the assertion or error (first lines), and whether it looks like a test problem or an application problem.

**Report format**
- Commit and tree state
- Tests: command, verbatim summary line, list of failures (or "none")
- Static checks: ruff / bandit / pip-audit one line each (pip-audit currently lists known vulnerable `starlette` and `pytest` versions; report what it shows now)
- Verdict: PASS only if the suite ran to completion with 0 failures; otherwise FAIL or NOT RUN, with the reason

If you ran only part of the suite (because arguments narrowed it), say so.
