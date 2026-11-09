"""Banking logic shared by the CLI and the web API. No I/O or framework code here."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bankapp import config
from bankapp.errors import AuthError, BankError, ClosedError, LockedError, NotFoundError
from bankapp.models import Account, Admin, AuthSession, Transaction
from bankapp.security import hash_pin, verify_pin

INVALID_LOGIN = "Invalid account number or PIN."


# ---------------------------------------------------------------- accounts

def _new_account_number(db: Session) -> str:
    while True:
        number = "".join(secrets.choice("0123456789") for _ in range(10))
        if not db.scalar(select(Account).where(Account.number == number)):
            return number


def open_account(db: Session, owner: str, pin: str) -> Account:
    owner = owner.strip()
    if not owner:
        raise BankError("Owner name is required.")
    if not (pin.isascii() and pin.isdigit() and len(pin) == 4):
        raise BankError("PIN must be exactly 4 digits.")
    account = Account(number=_new_account_number(db), owner=owner,
                      pin_hash=hash_pin(pin))
    db.add(account)
    db.commit()
    return account


# ---------------------------------------------------------------- sessions

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_token(db: Session, *, account: Account | None = None,
                 admin: Admin | None = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        token_hash=_hash_token(token),
        account_id=account.id if account else None,
        admin_id=admin.id if admin else None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=config.SESSION_MINUTES),
    ))
    db.commit()
    return token


def _live_session(db: Session, token: str) -> AuthSession | None:
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == _hash_token(token)))
    if session is None or session.expires_at <= datetime.now(timezone.utc):
        return None
    return session


def logout(db: Session, token: str) -> None:
    """End a session. Safe to call with an unknown or already-ended token."""
    session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == _hash_token(token)))
    if session is not None:
        db.delete(session)
        db.commit()


def account_for_token(db: Session, token: str) -> Account:
    session = _live_session(db, token)
    if session is None or session.account_id is None:
        raise AuthError("Not logged in.")
    return db.get(Account, session.account_id)


def admin_for_token(db: Session, token: str) -> Admin:
    session = _live_session(db, token)
    if session is None or session.admin_id is None:
        raise AuthError("Admin login required.")
    return db.get(Admin, session.admin_id)


# ------------------------------------------------------------------- login

def login(db: Session, number: str, pin: str) -> str:
    """Check the PIN and return a session token.

    After MAX_FAILED_ATTEMPTS wrong PINs in a row the account locks until an admin
    unlocks it. A successful login resets the counter.
    """
    # Row lock so two simultaneous wrong guesses can't both slip under the limit.
    account = db.scalar(select(Account).where(Account.number == number).with_for_update())
    if account is None:
        raise AuthError(INVALID_LOGIN)
    if account.locked:
        raise LockedError("Account is locked. Please contact an administrator.")

    if not verify_pin(pin, account.pin_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= config.MAX_FAILED_ATTEMPTS:
            account.locked = True
        db.commit()  # must persist before raising
        if account.locked:
            raise LockedError("Too many failed attempts. Account is locked; "
                              "please contact an administrator.")
        raise AuthError(INVALID_LOGIN)

    account.failed_attempts = 0
    return _issue_token(db, account=account)


# ------------------------------------------------------------------- admin

def ensure_admin(db: Session, username: str | None = None,
                 password: str | None = None) -> Admin:
    """Create the seeded admin if missing. An existing admin is left untouched."""
    username = username or config.ADMIN_USER
    password = password or config.ADMIN_PASSWORD
    admin = db.scalar(select(Admin).where(Admin.username == username))
    if admin is None:
        admin = Admin(username=username, password_hash=hash_pin(password))
        db.add(admin)
        db.commit()
    return admin


def admin_login(db: Session, username: str, password: str) -> str:
    admin = db.scalar(select(Admin).where(Admin.username == username))
    if admin is None or not verify_pin(password, admin.password_hash):
        raise AuthError("Invalid admin username or password.")
    return _issue_token(db, admin=admin)


def unlock_account(db: Session, number: str) -> Account:
    account = db.scalar(select(Account).where(Account.number == number).with_for_update())
    if account is None:
        raise NotFoundError("Account not found.")
    account.locked = False
    account.failed_attempts = 0
    db.commit()
    return account


# ------------------------------------------------------------ clock & hours

def utcnow() -> datetime:
    """The banking clock. Tests replace this to run at any time of day."""
    return datetime.now(timezone.utc)


def is_open(now: datetime | None = None) -> bool:
    """True during office hours: Monday-Friday, OPEN_HOUR <= local time < CLOSE_HOUR."""
    local = (now or utcnow()).astimezone(ZoneInfo(config.TIMEZONE))
    return local.weekday() < 5 and config.OPEN_HOUR <= local.hour < config.CLOSE_HOUR


def _hour_label(hour: int) -> str:
    suffix = "pm" if 12 <= hour < 24 else "am"
    return f"{hour % 12 or 12}{suffix}"


def closed_message() -> str:
    place = config.TIMEZONE.split("/")[-1].replace("_", " ")
    return (f"The bank is closed. Transactions are available Monday\u2013Friday, "
            f"{_hour_label(config.OPEN_HOUR)}\u2013{_hour_label(config.CLOSE_HOUR)} ({place} time).")


def require_open(now: datetime | None = None) -> None:
    if not is_open(now):
        raise ClosedError(closed_message())


# ---------------------------------------------------------- money movement

# Largest value the Numeric(12, 2) columns can hold.
MAX_BALANCE = Decimal("9999999999.99")


def parse_amount(value) -> Decimal:
    """Validate a money amount: positive, finite, at most 2 decimal places."""
    if isinstance(value, bool) or value is None:
        raise BankError("Invalid amount.")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise BankError("Invalid amount.")
    if not amount.is_finite():
        raise BankError("Invalid amount.")
    if amount <= 0:
        raise BankError("Amount must be greater than zero.")
    if amount != amount.quantize(Decimal("0.01")):
        raise BankError("Amount can have at most 2 decimal places.")
    if amount > MAX_BALANCE:
        raise BankError("Amount is too large.")
    return amount.quantize(Decimal("0.01"))


def _locked_account(db: Session, account: Account) -> Account:
    """Re-read the account with a row lock so concurrent updates can't lose money."""
    return db.scalar(select(Account).where(Account.id == account.id)
                     .with_for_update().execution_options(populate_existing=True))


def _record(db: Session, account: Account, kind: str, amount: Decimal,
            now: datetime | None = None, counterparty: str | None = None) -> Transaction:
    txn = Transaction(account_id=account.id, kind=kind, amount=amount,
                      balance_after=account.balance, counterparty=counterparty,
                      created_at=now or utcnow())
    db.add(txn)
    return txn


def get_balance(db: Session, account: Account) -> Decimal:
    db.refresh(account)
    return account.balance


def deposit(db: Session, account: Account, amount, now: datetime | None = None) -> Transaction:
    now = now or utcnow()
    require_open(now)
    amount = parse_amount(amount)
    account = _locked_account(db, account)
    if account.balance + amount > MAX_BALANCE:
        db.rollback()
        raise BankError("Deposit would exceed the maximum account balance.")
    account.balance += amount
    txn = _record(db, account, "deposit", amount, now)
    db.commit()
    return txn


# Transaction kinds that count towards the daily limit. Step 5 adds "transfer_out".
OUTGOING_KINDS = ("withdrawal", "transfer_out")


def local_day_bounds(day) -> tuple[datetime, datetime]:
    """UTC start and end of one local (business-timezone) calendar day.

    Computed from local midnights, so daylight-saving days (23 or 25 hours) are right.
    """
    tz = ZoneInfo(config.TIMEZONE)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """UTC start and end of the local calendar day containing `now`."""
    return local_day_bounds(now.astimezone(ZoneInfo(config.TIMEZONE)).date())


def sent_today(db: Session, account: Account, now: datetime | None = None) -> Decimal:
    start, end = day_bounds(now or utcnow())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.account_id == account.id,
            Transaction.kind.in_(OUTGOING_KINDS),
            Transaction.created_at >= start,
            Transaction.created_at < end,
        ))
    return Decimal(total)


def check_daily_limit(db: Session, account: Account, amount: Decimal,
                      now: datetime | None = None) -> None:
    remaining = max(config.DAILY_LIMIT - sent_today(db, account, now), Decimal("0"))
    if amount > remaining:
        raise BankError(
            f"Daily limit of ${config.DAILY_LIMIT:,.2f} exceeded. "
            f"You can still send ${remaining:,.2f} today.")


def withdraw(db: Session, account: Account, amount, now: datetime | None = None) -> Transaction:
    now = now or utcnow()
    require_open(now)
    amount = parse_amount(amount)
    account = _locked_account(db, account)  # lock first: the limit check must see every prior withdrawal
    try:
        if amount > account.balance:
            raise BankError("Insufficient funds.")
        check_daily_limit(db, account, amount, now)
    except BankError:
        db.rollback()  # release the row lock
        raise
    account.balance -= amount
    txn = _record(db, account, "withdrawal", amount, now)
    db.commit()
    return txn


def transfer(db: Session, sender: Account, to_number: str, amount,
             now: datetime | None = None) -> Transaction:
    """Move money between two accounts atomically. Returns the sender's ledger entry.

    Counts towards the sender's daily limit. A locked recipient can still receive.
    """
    now = now or utcnow()
    require_open(now)
    amount = parse_amount(amount)
    recipient = db.scalar(select(Account).where(Account.number == (to_number or "").strip()))
    if recipient is None:
        raise BankError("Recipient account not found.")
    if recipient.id == sender.id:
        raise BankError("You can't transfer to your own account.")

    # Lock both rows in a fixed order (lowest id first). Two people sending to each
    # other at the same moment then queue up instead of deadlocking.
    rows = db.scalars(
        select(Account).where(Account.id.in_([sender.id, recipient.id]))
        .order_by(Account.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    by_id = {a.id: a for a in rows}
    sender, recipient = by_id[sender.id], by_id[recipient.id]

    try:
        if amount > sender.balance:
            raise BankError("Insufficient funds.")
        check_daily_limit(db, sender, amount, now)
        if recipient.balance + amount > MAX_BALANCE:
            raise BankError("The recipient's account can't receive that amount.")
    except BankError:
        db.rollback()  # release both row locks
        raise

    sender.balance -= amount
    recipient.balance += amount
    out = _record(db, sender, "transfer_out", amount, now, counterparty=recipient.number)
    _record(db, recipient, "transfer_in", amount, now, counterparty=sender.number)
    db.commit()  # both balances and both ledger rows, or none
    return out
