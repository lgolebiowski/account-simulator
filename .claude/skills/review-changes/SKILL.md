---
name: review-changes
description: "Independent read-only code review of the changes since a base commit for architecture, layering, Decimal use, locking and transaction patterns, regression risk and test quality. Use after implementation and QA, before the orchestrator reports a feature as done."
argument-hint: "[base commit or branch, default HEAD~1]"
context: fork
agent: code-reviewer
background: false
---

# Code review

**Review range:** `$ARGUMENTS` if given, otherwise `HEAD~1`. Use `git diff <base>...HEAD` plus `git status` for uncommitted changes.

Follow your role instructions and the applicable `.claude/rules/*.md`. Check in particular:
1. No business rule outside `services.py` / `statements.py`; nothing duplicated across API, UI, CLI or tests.
2. No `float` or hand-rolled amount parsing; money only through Decimal and `parse_amount`.
3. Lock, then check, then change; ordered multi-row locks; one commit per unit of work; rollback on every failure path.
4. Contracts: service signatures, JSON shapes, status codes, CLI menu numbering and the tests that script it all agree.
5. Existing tests: none deleted, skipped or weakened. New tests prove the requirement (exact values, rejection paths, pinned clock, concurrency for money movement).
6. Ownership: changed files match the agents that should have changed them (`python3 .claude/hooks/audit-ownership.py` helps).

Run `.claude/bin/test.sh` if your verdict depends on it, and quote the summary line. Report in your role's format. You are read-only: do not fix anything.
