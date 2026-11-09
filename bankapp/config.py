import os
from decimal import Decimal

DATABASE_URL = os.environ.get(
    "BANK_DATABASE_URL",
    "postgresql+psycopg://bank:bank@localhost:5434/bank",
)

# Seeded admin. Defaults are for local development only; set the env vars for anything real.
ADMIN_USER = os.environ.get("BANK_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("BANK_ADMIN_PASSWORD", "admin123")

SESSION_MINUTES = 30
MAX_FAILED_ATTEMPTS = 3

# Business timezone: office hours (step 6) and the daily-limit reset both use it.
TIMEZONE = os.environ.get("BANK_TIMEZONE", "Australia/Sydney")

# Office hours, Monday-Friday in TIMEZONE: open from OPEN_HOUR:00:00 up to, but not
# including, CLOSE_HOUR:00:00 (so 17:00 sharp is closed). The env vars let you demo the
# app after hours; the Mon-Fri rule is fixed.
OPEN_HOUR = int(os.environ.get("BANK_OPEN_HOUR", "8"))
CLOSE_HOUR = int(os.environ.get("BANK_CLOSE_HOUR", "17"))

# Total money allowed out of one account per local calendar day
# (withdrawals now; transfers count towards it too once they exist).
DAILY_LIMIT = Decimal("10000.00")
