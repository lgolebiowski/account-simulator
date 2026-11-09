---
name: add-banking-operation
description: "Checklist for adding a new account operation (a new way money moves or a new account action) across every layer in the right order: schema, service, API, browser UI, CLI, statements and tests. Use when planning or implementing something like fees, interest, closing an account, scheduled payments or limits."
argument-hint: "[operation name]"
---

# Adding a banking operation: $ARGUMENTS

Work through these in order. The owner of each step is in brackets.

1. **Schema** (database-engineer). New column or table? Add it in `models.py`; if it alters an existing table add the idempotent `ALTER ... IF NOT EXISTS` to `init_db` with an upgrade test. New ledger `kind`? It is just a string, no schema change.
2. **Service** (backend-engineer), in `bankapp/services.py`:
   ```python
   def operation(db, account, amount, now=None):
       now = now or utcnow()
       require_open(now)                  # if it moves money
       amount = parse_amount(amount)      # Decimal, 2 dp, > 0, <= MAX_BALANCE
       account = _locked_account(db, account)   # several accounts: lock in id order in one query
       try:
           ...checks inside the lock (balance, check_daily_limit, caps)...
       except BankError:
           db.rollback(); raise
       account.balance += / -= amount
       txn = _record(db, account, "kind", amount, now, counterparty=...)
       db.commit()                        # balance(s) and ledger row(s) together
       return txn
   ```
3. **Limits and statements** (backend-engineer). Money going out? Add the kind to `OUTGOING_KINDS` so the daily limit counts it. Add the kind to `statements.SIGN` and `statements.LABEL`; check the CSV and the UI table show it correctly.
4. **API** (backend-engineer), in `api.py`: pydantic request model; route using `current_account` (or `current_admin`); one service call; response model with no secrets. New `BankError` subclass in `errors.py` only if a new status code is needed.
5. **Contract frozen, then in parallel:**
   - **Browser UI** (frontend-engineer): form in `index.html`, handler in `app.js` using `run()`, `checkAmount()`, `money()`, `refreshStatement()`; `textContent` only.
   - **CLI** (cli-engineer): menu entry, Log out stays last, and every test that scripts the menu is renumbered.
6. **Tests** (each owner; QA for the independent pass): service happy path and every rejection with "nothing changed"; after-hours refusal; daily limit; statement line and CSV; API status codes, auth and per-user isolation; UI file checks; CLI flow; **a concurrency test**; and a regression run of the whole suite.
7. **Review:** `/bank-security-audit` and `/review-changes`.

Do not copy a rule into the API, UI or CLI. If a layer needs it, expose a function in services.
