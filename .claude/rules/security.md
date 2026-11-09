---
paths:
  - "bankapp/**/*.py"
  - "bankapp/static/**"
  - "cli.py"
---

# Security controls to preserve

## Credentials
- PINs (4 ASCII digits) and admin passwords are hashed with scrypt through `security.hash_pin` / `verify_pin` (constant-time compare). Never store, log, print or return a PIN, password, hash or token.
- The seeded admin defaults to `admin` / `admin123` for local development only; real use must set `BANK_ADMIN_USER` / `BANK_ADMIN_PASSWORD`.

## Login and lockout
- Unknown account and wrong PIN return the **same** error, so account numbers can't be probed.
- The lockout check runs before the PIN check. Failures are counted under a row lock; three in a row lock the account until an admin unlocks it; a success resets the count. Unlock is admin-only.

## Sessions and authorization
- Tokens are `secrets.token_urlsafe(32)`; only their SHA-256 is stored; they expire after `SESSION_MINUTES` (30); logout deletes the session.
- A session belongs to **either** an account **or** an admin. An account token must never pass `current_admin`, and the reverse.
- "Whose data?" always comes from the token (`current_account`). Never trust an account id or number in the request body or URL for the caller's own data. Every query for statements, balance or ledger filters by `account.id`.
- New endpoints need an explicit decision: public, account, or admin. Default to account.

## Output and input
- Response models must not expose `pin_hash`, `password_hash`, token hashes or `failed_attempts`.
- CSV and statements contain only system-generated values, never user-typed text, so they can't carry spreadsheet formulas.
- Browser: set text with `textContent`, never insert HTML; no inline `<script>` or `on*=` handlers (the CSP is `default-src 'self'`); keep the token in `sessionStorage` only, never in a URL, a log or `localStorage`.
- Error messages explain what the user can fix and never expose internals (SQL, stack traces, file paths).
- Keep the CSP, `X-Content-Type-Options` and `Cache-Control: no-store` headers on the page response.
