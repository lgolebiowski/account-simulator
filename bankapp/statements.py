"""Account statements: a date range of ledger entries, as lines or as CSV."""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankapp import config, services
from bankapp.errors import BankError
from bankapp.models import Account, Transaction

DEFAULT_DAYS = 30

# Money in is positive, money out is negative.
SIGN = {"deposit": 1, "transfer_in": 1, "withdrawal": -1, "transfer_out": -1}
LABEL = {"deposit": "Deposit", "withdrawal": "Withdrawal",
         "transfer_out": "Transfer out", "transfer_in": "Transfer in"}

CSV_HEADER = ["Date", "Time", "Type", "Other account", "Amount", "Balance"]


@dataclass
class Line:
    time: datetime          # local (business timezone) time
    type: str               # a LABEL value
    amount: Decimal         # signed
    other_account: str | None
    balance: Decimal        # balance after this entry


@dataclass
class Statement:
    start: date
    end: date
    lines: list[Line]       # oldest first


def resolve_range(start: date | None, end: date | None,
                  now: datetime | None = None) -> tuple[date, date]:
    """Fill in defaults (the last 30 days, ending today) and check the order."""
    today = (now or services.utcnow()).astimezone(ZoneInfo(config.TIMEZONE)).date()
    end = end or today
    start = start or end - timedelta(days=DEFAULT_DAYS - 1)
    if start > end:
        raise BankError("The start date must be on or before the end date.")
    return start, end


def get_statement(db: Session, account: Account, start: date | None = None,
                  end: date | None = None, now: datetime | None = None) -> Statement:
    """Entries from the start of `start` to the end of `end`, both days inclusive."""
    start, end = resolve_range(start, end, now)
    lo = services.local_day_bounds(start)[0]
    hi = services.local_day_bounds(end)[1]
    rows = db.scalars(
        select(Transaction)
        .where(Transaction.account_id == account.id,
               Transaction.created_at >= lo, Transaction.created_at < hi)
        .order_by(Transaction.created_at, Transaction.id)).all()
    tz = ZoneInfo(config.TIMEZONE)
    lines = [Line(time=t.created_at.astimezone(tz), type=LABEL[t.kind],
                  amount=SIGN[t.kind] * t.amount, other_account=t.counterparty,
                  balance=t.balance_after) for t in rows]
    return Statement(start, end, lines)


def to_csv(statement: Statement) -> str:
    """Plain numbers (-250.00 / 250.00) so it opens cleanly in a spreadsheet."""
    out = io.StringIO()
    writer = csv.writer(out)  # CRLF line endings, the CSV standard
    writer.writerow(CSV_HEADER)
    for line in statement.lines:
        writer.writerow([line.time.strftime("%Y-%m-%d"), line.time.strftime("%H:%M:%S"),
                         line.type, line.other_account or "",
                         f"{line.amount:.2f}", f"{line.balance:.2f}"])
    return out.getvalue()
