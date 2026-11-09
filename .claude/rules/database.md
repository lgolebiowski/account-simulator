---
paths:
  - "bankapp/models.py"
  - "bankapp/db.py"
  - "bankapp/services.py"
  - "bankapp/statements.py"
  - "docker-compose.yml"
  - "tests/conftest.py"
  - "tests/test_db_*.py"
---

# Database, transactions and concurrency

## Locking and commits (money-changing code)
- Lock first, then check, then change: `_locked_account(db, account)` re-reads the row `FOR UPDATE` with `populate_existing`. Every balance check and daily-limit check happens **inside** the lock, or two simultaneous requests can both pass it.
- Several rows (transfers): lock them in **one query ordered by id** so opposite transfers queue instead of deadlocking.
- A validation failure after locking calls `db.rollback()` before raising, to release the locks.
- One `db.commit()` per operation covers the balance change(s) **and** the ledger row(s). Never commit between them.
- Add a concurrency test (threads, one session each) for anything that moves money. Existing examples: `test_concurrent_deposits_*`, `test_concurrent_transfers_cannot_beat_the_limit`, `test_opposite_transfers_*`.

## Schema changes
- `Base.metadata.create_all` creates missing tables but **never alters existing ones**. A new column on an existing table needs an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `init_db`, plus a test that an old table gets upgraded (see `test_init_db_adds_counterparty_...`).
- There is no migration tool. Do not add Alembic without the user's approval; propose it instead.
- Timestamps are `timestamptz` and stored in UTC. Convert to the business timezone only for display and day boundaries (`services.local_day_bounds`).
- Money columns are `Numeric(12, 2)`.

## Environments
- Dev database: Docker Postgres, host port **5434**, database `bank`. Do not modify its data; never run `docker compose down -v`.
- Tests use `bank_test` (or `bank_test_<hash>` in a worktree); every test drops and recreates the tables. The name is validated before it goes into `CREATE DATABASE`.
- Never build SQL by string formatting. Use SQLAlchemy constructs or bound parameters.
