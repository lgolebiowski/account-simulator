---
paths:
  - "cli.py"
  - "tests/test_cli.py"
---

# CLI rules

- `cli.py` is a thin adapter: prompt, call `services` / `statements`, print. No SQL and no business rules.
- Secrets are read with `getpass` and never echoed. Account numbers and amounts use `input`.
- A `BankError` is printed as `Error: <message>` and `main()` returns 1; success returns 0; bad usage returns 2.
- The account menu keeps **Log out as the last number**. Adding or moving an option changes the numbers that tests feed in, so update every test that scripts the menu: `tests/test_cli.py`, the CLI test in `tests/test_office_hours.py`, and the CLI tests in `tests/test_statement.py`.
- Money is displayed with `f"{value:,.2f}"` on a Decimal. Never convert it to float.
- Anything written to disk uses mode `"x"` (never overwrite) and reports a failure as a `BankError`.
- `main()` runs `init_db()` and `ensure_admin` first; tests replace `cli.SessionLocal` and `cli.init_db` (see the `wire`/`wired` helpers).
- Test by scripting `input` and `getpass`; assert on printed output and on database state.
