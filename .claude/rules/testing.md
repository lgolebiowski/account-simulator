---
paths:
  - "tests/**"
---

# Testing rules

- Run with `.claude/bin/test.sh` (needs the Docker database). It fails loudly if Postgres is down; a run that never touched the database is not a pass.
- **Time is pinned.** An autouse fixture sets the banking clock to Tuesday 10 March 2026, 12:00 Sydney (inside office hours). Move it with `set_clock(datetime)`. Pass `now=` to service functions for specific moments. Tests that probe midnight or other hours patch `config.OPEN_HOUR` / `config.CLOSE_HOUR` (see `test_withdraw.py`). Never depend on the real clock or the day of the week.
- Fixtures: `db` (a session on freshly emptied tables), `session_factory` (for threads and the CLI), `client` (FastAPI `TestClient` on that session), `admin`, `fixed_clock`, `set_clock`.
- Every feature gets tests at each layer it touches (service, API, UI file checks, CLI), including: the happy path, each rejection path with "nothing changed" assertions, bad input, after-hours behaviour, and the daily limit where money moves.
- Anything that moves money also gets a **concurrency test** (threads, a separate session each) proving no lost updates and no deadlocks.
- Add to existing files by feature; name new service/API files `tests/test_<feature>.py`, database ones `tests/test_db_<topic>.py`.
- **Never delete, weaken or skip a test or assertion to get green.** If a test is wrong, fix it and say why in your report. If a test fails because the application is wrong, report it; do not touch application code unless you own it.
- Assert exact values (`Decimal("10.50")`, specific status codes and messages), not just "no exception".
- Use only the test database. Never read or write the dev database `bank`.
