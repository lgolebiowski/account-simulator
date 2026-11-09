---
name: bank-security-audit
description: "Independent read-only security audit of the bank app or of changes since a base commit: authentication, lockout, sessions, authorization, injection, XSS/CSP, business-rule bypass and dependency vulnerabilities. Use after implementing a feature or on demand."
argument-hint: "[base commit or branch, blank = whole app]"
context: fork
agent: security-reviewer
background: false
---

# Security audit

**Scope:** $ARGUMENTS (if blank, audit the whole application; otherwise focus on `git diff $ARGUMENTS...HEAD` plus uncommitted changes, but still trace any code those changes call).

Follow your role instructions and `.claude/rules/security.md`. Specifically:
1. Run `.claude/bin/audit.sh` and include the bandit and pip-audit results.
2. Enumerate every route in `bankapp/api.py` and state its auth requirement (public / account / admin). Flag any that is not explicit.
3. Try to break each control on paper with a concrete scenario: probing account numbers, brute-forcing a PIN across concurrent requests, using an account token on an admin route, reading or moving another user's money, bypassing the daily limit or office hours via another route or the CLI, negative / NaN / huge amounts, XSS through account names, CSV formula injection, replaying an expired or logged-out token.
4. Report with the table format from your role instructions. Distinguish confirmed from suspected findings, name the owner agent for each, and list the areas you checked with no findings.

You are read-only. Do not fix anything.
