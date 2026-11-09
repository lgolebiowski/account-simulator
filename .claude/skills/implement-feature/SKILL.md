---
name: implement-feature
description: "Run a feature or non-trivial change through the full multi-agent workflow with quality gates (inspect, spec, delegate by file ownership, implement with tests, QA, security and code review, regression, report). Use when the user asks to add or change banking functionality."
argument-hint: "[feature description]"
disable-model-invocation: true
---

# Implement a feature through the agent workflow

**Request:** $ARGUMENTS

You are the Orchestrator. Follow every gate in order; do not skip one. If a requirement is ambiguous, **ask the user instead of assuming**.

## 0. Preflight
- `git status --short` should be clean; if not, tell the user what is uncommitted and ask before continuing.
- Confirm the database is up and record the **baseline**: run `.claude/bin/test.sh` and note the exact summary line (for example `209 passed`) and the current commit (`git rev-parse --short HEAD`). Regressions are judged against this.

## 1. Inspect
Read the code and tests the change will touch before planning: `bankapp/services.py`, `api.py`, `statements.py`, `models.py`, and the relevant UI, CLI and test files. Read `.claude/rules/*.md` that apply. Use the `Explore` agent only if the search is wide.

## 2. Spec and plan
Write down (briefly):
- Requirements and acceptance criteria; edge cases (limits, after-hours, concurrency, bad input, permissions).
- Affected layers: schema, services, API, UI, CLI, tests.
- **The contract:** service function signatures and errors, API paths, request/response JSON, status codes, UI and CLI behaviour.
- A task table: task, agent, files it will touch (check `.claude/ownership.json`), depends on.
Show the plan to the user and wait for approval when the change is large, risky, touches money rules or security, or changes the schema.

## 3. Delegate in dependency order
Brief each agent with: the spec and contract, its files, how to test (`.claude/bin/test.sh <files>`), the report format, and that it must not edit files it does not own.
1. **database-engineer**, only if the schema or locking changes. Commit its result on `main`.
2. **backend-engineer**: services, then API, with tests. Commit on `main`.
3. **frontend-engineer** and **cli-engineer** **in parallel** (single message, two Agent calls). They run in isolated worktrees that branch from `main`, so everything above must already be committed. Never edit the same file in two places at once.
4. **qa-engineer**: brief it with the spec, contract and acceptance criteria, **not** the implementers' summaries, so it stays independent.
The agent roster and ownership are in `CLAUDE.md`. Independent features may run backend agents in parallel with `isolation: "worktree"` on the call.

## 4. After each agent returns
- Ownership audit: `python3 .claude/hooks/audit-ownership.py --agent <name> --base <commit before it started>` must exit 0. A violation means revert that file and re-route the change to its owner.
- Merge worktree branches into `main` (`git merge --no-ff <branch>`), resolve conflicts yourself, run the affected tests, commit with the `Co-Authored-By` trailer from CLAUDE.md. Remove merged worktrees and their test databases (see docs).
- If an agent reports "changes needed in files I don't own", route them to the owner now.

## 5. Full regression (you run it)
Run `.claude/bin/test.sh` yourself. Compare to the baseline: nothing that passed may now fail; test count should have grown. If anything fails, find the cause and send it back to the owning agent; do not edit tests to make them pass.

## 6. Independent reviews (parallel)
Run `/bank-security-audit <baseline commit>` and `/review-changes <baseline commit>` together. Triage: fix Critical/High and Must-fix items through their owners and repeat steps 4 and 5; list the rest as outstanding risks.

## 7. Report to the user
- **Changed files** (grouped by layer).
- **Tests:** the exact commands you ran and their verbatim summary lines: baseline vs final. Say which suites you did **not** run.
- **Reviews:** findings and how each was resolved or why it is outstanding.
- **Outstanding risks and anything not done.**
- Update `CLAUDE.md`, `.claude/rules/` or `docs/` if a convention changed.

**Never say tests pass unless you ran them in this session and saw the output.**
