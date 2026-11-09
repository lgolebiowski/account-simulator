---
paths:
  - "bankapp/static/**"
  - "tests/test_ui.py"
---

# Browser UI rules

- Plain HTML, CSS and JavaScript. No framework, no bundler, no CDN, no external fonts or scripts: the CSP only allows the page's own files.
- Files: `index.html` (structure), `style.css` (CSS variables, light/dark via `prefers-color-scheme`), `app.js` (behaviour). No inline `<script>`, `style=` handlers or `on*=` attributes.
- Put text on the page with `textContent`, `insertRow`/`insertCell`, `replaceChildren`. Never `innerHTML` or similar. `tests/test_ui.py` fails the build if it finds them.
- Every id that `app.js` reads must exist in `index.html` (also tested). Add the element and the code in the same change.
- Amounts are strings end to end. Format with string operations (`money()`), never `parseFloat`/`Number` on money.
- Use the existing helpers: `api()` (adds the token, turns a 401 into "session ended"), `run(form, work)` (disables the button, shows errors), `showMessage`, `checkAmount`, `refreshStatement`.
- The server is authoritative. Client checks are only courtesy hints; never rely on them for correctness.
- Accessibility: every input has a visible `<label>`; messages use `role="status"`/`aria-live`; buttons are real `<button>`s; keep focus outlines. Layout must work at phone width with no horizontal page scroll (wrap wide tables in `.table-wrap`).
- Session state lives in `sessionStorage`, wrapped in try/catch.
- After editing run `node --check bankapp/static/app.js`. Where a browser is available, click through the changed flow and say what you could not check.
