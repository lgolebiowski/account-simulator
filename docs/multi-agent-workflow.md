# Multi-agent development workflow

The main Claude Code session is the **Orchestrator / Technical Lead**. It plans, delegates to
specialist subagents, integrates their work and reports. The specialists are plain subagents:
each has its own context, a restricted toolset and a fixed set of files it may edit.

```
                       Orchestrator (main session)
        plans · delegates · merges · runs the regression · reports
                                 │
   ┌──────────────┬──────────────┼──────────────┬───────────────┐
 database ─────▶ backend ──┬──▶ frontend (worktree)             │
 (schema,        (services, │                                    ▼
  locking)        API)      └──▶ cli (worktree)  ──▶  qa  ──▶  security-reviewer ┐ in
                                                  (independent)  code-reviewer   ┘ parallel
```

## Who does what

| Agent | Responsible for | May edit | Model |
|---|---|---|---|
| **backend-engineer** | Business rules, REST API, auth flow, error mapping | `api.py`, `services.py`, `statements.py`, `errors.py`, `config.py`, `security.py`, service/API tests | inherit |
| **database-engineer** | Tables, schema upgrades, transactions, locking, concurrency | `models.py`, `db.py`, `docker-compose.yml`, `tests/test_db_*.py` | inherit |
| **frontend-engineer** | Browser UI (HTML/CSS/JS, no framework) | `bankapp/static/**`, `tests/test_ui.py` | sonnet, worktree |
| **cli-engineer** | Terminal menus and workflows | `cli.py`, `tests/test_cli.py` | sonnet, worktree |
| **qa-engineer** | Regression, integration and edge-case tests, test infrastructure | `tests/**` (never application code) | sonnet |
| **security-reviewer** | Auth, sessions, authorization, injection/XSS, dependencies | nothing (read-only) | inherit |
| **code-reviewer** | Architecture, layering, quality, regression risk | nothing (read-only) | inherit |
| **Orchestrator** | `CLAUDE.md`, `.claude/**`, `docs/**`, `requirements*.txt`, `ruff.toml`, merges | | your session's |

`database-engineer` cannot edit `services.py`. When a lock or query there must change, it returns
the exact snippet and the orchestrator routes it to `backend-engineer`. One owner per file at a time.

Reviewers and QA are independent of the implementers: QA is briefed with the spec and contract, not
the implementers' summaries; the reviewers cannot edit anything.

## How the rules are enforced

| Mechanism | File | What it does |
|---|---|---|
| Shared instructions | `CLAUDE.md` | Architecture, constraints, delegation table, quality gates. Loaded by every agent |
| Domain rules | `.claude/rules/*.md` | money, layering, database, security, frontend, CLI, testing. Each loads only when matching files are touched |
| Ownership map | `.claude/ownership.json` | Single source of truth for who may edit what |
| **Edit guard** | `.claude/hooks/guard-paths.py` | A `PreToolUse` hook in each agent's frontmatter blocks Edit/Write outside its files. Fails closed |
| **Ownership audit** | `.claude/hooks/audit-ownership.py` | The orchestrator runs it after each agent: lists changed files the agent doesn't own. Catches shell-based edits the guard can't see |
| **Fast checks** | `.claude/hooks/post-edit-check.py` | `PostToolUse` on every Edit/Write: Python compiles, no `float` in money code, ruff, `node --check` for JS, JSON validity. Problems go straight back to the agent |
| Permissions | `.claude/settings.json` | Denies `git push`, `git reset --hard`, `docker compose down -v` and volume deletion; allows the test/audit/read-only git commands |
| Test runner | `.claude/bin/test.sh` | Runs pytest from the main checkout or a worktree. Refuses to run, loudly, if Postgres is down: a run that never touched the database is not a pass |
| Static checks | `.claude/bin/audit.sh` | ruff, bandit, pip-audit |

There is deliberately **no automatic full-suite run** at the end of a turn. Run `/run-regression`
when you want the complete result.

## Skills (reusable workflows)

| Command | Purpose |
|---|---|
| `/implement-feature <description>` | The full gated workflow: inspect, spec, delegate by ownership, implement with tests, QA, reviews, regression, report. Manual only |
| `/add-banking-operation <name>` | Layer-by-layer checklist for a new money operation (schema, service, limits, statements, API, UI, CLI, tests) |
| `/run-regression [pytest args]` | Full suite plus ruff/bandit/pip-audit, reported honestly, in a forked QA agent. Fixes nothing |
| `/bank-security-audit [base]` | Independent read-only security audit in a forked security-reviewer |
| `/review-changes [base]` | Independent read-only code review in a forked code-reviewer |

## The gates every feature passes
1. Inspect existing code and tests. 2. Spec, contract and ownership plan (the user approves large or risky ones).
3. Delegate in order: database → backend → frontend ∥ CLI → QA. 4. Ownership audit and merge after each agent.
5. Orchestrator runs the **full regression** and compares with the baseline. 6. Security and code review in parallel.
7. Report: changed files, exact test commands and verbatim results, outstanding risks.
**Tests are never reported as passing unless they were run and the output seen.**

## Worktrees
`frontend-engineer` and `cli-engineer` run with `isolation: worktree`, so they can work at the same time.
- A worktree branches from the **committed** `main`: commit each finished stage first, or the agent will not see it.
- An agent in a worktree commits on its own branch and reports the branch. Merge:
  `git merge --no-ff <branch>`, resolve conflicts, run the tests, then
  `git worktree list`, `git worktree remove <path>`, `git branch -d <branch>`.
- Each worktree automatically uses its own test database (`bank_test_<hash>`), so parallel test runs
  cannot wipe each other. Clean up leftovers:
  `docker exec python-bank-app-db-1 psql -U bank -d bank -Atc "select datname from pg_database where datname like 'bank_test_%'"`
  then `... -c "DROP DATABASE bank_test_<hash>"` for any whose worktree is gone.
- To run two independent backend features at once, call the agent with `isolation: "worktree"`.

## Example prompts

**A whole feature (recommended):**
> `/implement-feature Let a customer close their account: allowed only when the balance is 0, blocks login afterwards, available in the web page and the CLI, and shown as the last line of the statement.`

**A new money operation, planned first:**
> `/add-banking-operation monthly account fee` then: "Draft the plan and contract only, don't implement yet."

**Targeted delegation:**
> Use the database-engineer to review `transfer()` for deadlocks and lost updates, and have it write concurrency tests. Report what it wants changed in `services.py`.

**Independent checks before a release:**
> Run `/run-regression`, then `/bank-security-audit` and `/review-changes main~3` in parallel, and summarise everything that needs fixing, by owner.

**UI-only change:**
> Use the frontend-engineer to show the daily limit remaining on the dashboard. The backend contract is `GET /limits` returning `{"remaining": "6499.50"}`. (If that endpoint doesn't exist yet, `/implement-feature` it first.)

**Pre-existing issues (good first uses):**
> Upgrade the vulnerable dependencies reported by `.claude/bin/audit.sh` (starlette, pytest) and run the full regression.

## Agent Teams (optional, off by default)
Agent Teams (teammates that message each other) are experimental and cost far more tokens. They are
**not** enabled here. Where they would help: a parallel adversarial security + code review, or
debugging a concurrency bug with competing hypotheses. To try one for a single session:
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude`, then ask for teammates using the
`security-reviewer` and `code-reviewer` agent types. Enabling them globally also makes any
subagent Claude names start as a teammate, so keep them off otherwise.

## Known limits and baseline findings
- **New agents load only after a restart** of the Claude Code session (editing existing ones is picked up live). Skills, rules, hooks and `settings.json` apply immediately.
- The edit guard covers Edit/Write, not shell redirects (`sed -i`, `>`). Agents are told not to, and `audit-ownership.py` catches it afterwards.
- **`pip-audit` reports known vulnerabilities** in the pinned `starlette` (via FastAPI 0.115.6) and `pytest 8.3.4`. Not fixed here because it changes the app's dependencies; a good first `/implement-feature`.
- **Ruff baseline:** 3 `raise ... from` findings (`services.py`, `cli.py` ×2) and 2 unused imports in tests are listed under `per-file-ignores` in `ruff.toml`. Fix them and delete those lines.
- `requirements-dev.txt` adds ruff, bandit and pip-audit; the app itself still needs only `requirements.txt`.
