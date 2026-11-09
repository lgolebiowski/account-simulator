---
paths:
  - "bankapp/**/*.py"
  - "bankapp/static/**"
  - "cli.py"
---

# Layering: one place for business rules

- **Rules live in `services.py` and `statements.py`.** That includes validation, limits, lockout, office hours, balance checks, ledger writing and anything that decides whether money may move.
- **`api.py` is an adapter:** pydantic models for request/response shape, one service call per route, `current_account` / `current_admin` for auth. No SQL, no money arithmetic, no rules. Errors come from services as `BankError` subclasses; the app-wide handler turns them into JSON with the subclass's `status_code`.
- **`cli.py` is an adapter:** prompts, `print`, and calls into services. No SQL, no rules.
- **The browser page is an adapter:** formatting and courtesy checks (empty field, amount shape) only. The server is authoritative; a client-side check never replaces a service check.
- Adding a rule: write it in services first, then expose it. If two layers seem to need the same logic, add one function to services and call it from both. Never copy it.
- Services take the `Session` and the already-authenticated `Account`; they commit their own unit of work. Routes and menus do not commit.
- New error cases: reuse an existing `BankError` subclass, or add one to `errors.py` with its status code.
- When a layer-specific need changes a contract (service signature, JSON shape, status code), tell the orchestrator so the other layers and tests are updated together.
