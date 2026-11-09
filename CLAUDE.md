# Python Bank App

A simple banking app: open accounts, PIN login with lockout, deposits, withdrawals, transfers,
statements (CSV), office hours, daily limit. Three front ends share one set of business rules.

## Commands
- Database (Docker, host port **5434**): `docker compose up -d --wait`
- Web app + API: `.venv/bin/uvicorn bankapp.api:app --port 8000` (page at `/`, API docs at `/docs`)
- CLI: `.venv/bin/python cli.py open | login | unlock <account>`
- Tests (needs the database up): `.claude/bin/test.sh [pytest args]`. Works from a worktree too.
- Static checks: `.claude/bin/audit.sh` (ruff, bandit, pip-audit)
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`

## Architecture (do not change without the user's approval)
Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2, plain HTML/CSS/JS (no framework, no build step).

| Path | Role |
|---|---|
| `bankapp/services.py` | **The single source of truth for banking rules.** Accounts, login/lockout, deposit/withdraw/transfer, daily limit, office hours, admin |
| `bankapp/statements.py` | Statement lines and CSV |
| `bankapp/api.py` | FastAPI routes: thin adapter over services |
| `bankapp/models.py`, `db.py` | SQLAlchemy tables, engine, `init_db` |
| `bankapp/security.py` | scrypt hashing for PINs and admin passwords |
| `bankapp/errors.py` | `BankError` and subclasses; each carries its HTTP status |
| `bankapp/config.py` | Settings and env vars |
| `bankapp/static/` | Browser UI: `index.html`, `app.js`, `style.css` |
| `cli.py` | Terminal menu: thin adapter over services |
| `tests/` | pytest, against a separate test database |

## Hard constraints
1. **Never duplicate business logic.** A rule lives in `services.py`/`statements.py`; the API, UI and CLI call it. If a second layer needs a rule, expose a function in services.
2. **Money is `Decimal`, never `float`.** Amounts enter through `services.parse_amount`. JSON carries amounts as strings.
3. **Keep transaction integrity.** Money-changing code locks account rows (`with_for_update`), checks inside the lock, and commits balances and ledger rows together. See `.claude/rules/database.md`.
4. **Keep the security controls** in `.claude/rules/security.md`: hashed PINs, hashed tokens, generic login errors, lockout, scoped admin tokens, CSP, no HTML injection.
5. **Time goes through `services.utcnow()`** so tests can pin it. Office hours and the daily limit use the business timezone (`BANK_TIMEZONE`, default Australia/Sydney).
6. The user's **dev server (:8000) and dev database (`bank`) may be in use.** Do not start, stop or modify them. Tests use their own database.

## Working model: orchestrator and specialists
The main session is the **Orchestrator / Technical Lead**: it plans, delegates, integrates and reports. Small single-file fixes may be done directly; anything bigger goes through `/implement-feature`.

| Agent | Owns (may edit) |
|---|---|
| `backend-engineer` | `api.py`, `services.py`, `statements.py`, `errors.py`, `config.py`, `security.py`, service/API tests |
| `database-engineer` | `models.py`, `db.py`, `docker-compose.yml`, `tests/test_db_*.py` |
| `frontend-engineer` | `bankapp/static/**`, `tests/test_ui.py` |
| `cli-engineer` | `cli.py`, `tests/test_cli.py` |
| `qa-engineer` | `tests/**` (including `conftest.py`), never application code |
| `security-reviewer`, `code-reviewer` | nothing: read-only, they report |
| Orchestrator | `CLAUDE.md`, `.claude/**`, `docs/**`, `requirements*.txt`, `ruff.toml`, merges |

The exact rules are in `.claude/ownership.json`; a hook blocks out-of-ownership edits, and `.claude/hooks/audit-ownership.py` checks after the fact. One owner per file at a time. If you need a change in someone else's file, say so in your report; do not edit it, and do not use shell commands to get around the block.

Order of work: database, then backend, then frontend and CLI in parallel (worktrees), then QA, then security and code review in parallel, then the orchestrator integrates. Details: `docs/multi-agent-workflow.md`.

## Quality gates (every feature)
1. Read the existing code and tests first.
2. Write down requirements, affected layers and the API contract. Ask the user when something is ambiguous; do not assume.
3. Delegate by ownership. Implement with tests.
4. Run the affected tests, then the **full suite** (`.claude/bin/test.sh`).
5. Independent QA, then security and code review.
6. Report: changed files, test results, outstanding risks.

**Never say tests pass unless you ran them in this session and saw the output.** Quote the pytest summary line. If the database was down or a command failed, say so. Never delete, weaken or skip a test to get green.

## Git and worktrees
- Branch `main`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Never push; never `reset --hard`.
- A worktree branches from the committed `main`, so **commit finished stages before starting the next parallel one**.
- An agent running in a worktree commits on its own branch and reports the branch and commit; the orchestrator merges. Agents on `main` do not commit.
- Worktrees get their own test database automatically (`bank_test_<hash>`), so parallel test runs are safe.
- Never run `docker compose down -v` (it deletes the database volume).

## Agent report format
Every specialist ends with: **Changed files**, **Commands run and their results** (verbatim summary lines), **Risks / not done**, and, if it hit an ownership block, **Changes needed in files I don't own**.
