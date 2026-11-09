---
paths:
  - "bankapp/**/*.py"
  - "cli.py"
  - "tests/**/*.py"
---

# Money rules

- All money is `decimal.Decimal`. Never `float`, never a float literal, never `round()` on money. A hook rejects `float` in `bankapp/` and `cli.py`.
- User-supplied amounts go through `services.parse_amount`: finite, greater than zero, at most 2 decimal places, at most `MAX_BALANCE`. It **rejects** bad input (for example `1.234`); it never rounds. Do not write a second parser.
- Database columns are `Numeric(12, 2)`. Do the arithmetic in Python with Decimal, inside the row lock.
- The ledger (`transactions.amount`) is always positive; `kind` gives the direction. Signed amounts exist only in statements (`statements.SIGN`).
- JSON carries amounts as strings (`"250.00"`); the API returns Decimals, which serialise as strings. The browser formats with string operations, not `Number`/`parseFloat`.
- Format only at the edge: `f"{amount:,.2f}"` is fine on a Decimal. CSV uses plain `f"{amount:.2f}"` with no thousands separator.
- In tests compare Decimals (`Decimal("10.50")`), not floats or rounded strings of floats.
