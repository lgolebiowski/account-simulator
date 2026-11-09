from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from bankapp import config, services
from bankapp.errors import BankError
from bankapp.models import Account, Transaction

SYD = ZoneInfo("Australia/Sydney")
D = Decimal


def at(y, mo, d, h=12, mi=0, s=0):
    """A moment given in Sydney local time."""
    return datetime(y, mo, d, h, mi, s, tzinfo=SYD)


@pytest.fixture(autouse=True)
def sydney(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Australia/Sydney")
    # These tests probe the midnight limit reset, so open the bank 24h (hours have their own tests).
    monkeypatch.setattr(config, "OPEN_HOUR", 0)
    monkeypatch.setattr(config, "CLOSE_HOUR", 24)


@pytest.fixture
def ann(db):
    acct = services.open_account(db, "Ann", "1234")
    services.deposit(db, acct, "50000")  # plenty, so the daily limit is what bites
    return acct


NOON = at(2026, 3, 10)  # a normal (AEDT) day


# ----------------------------------------------------------- basic withdraw

def test_withdraw_reduces_balance_and_records_transaction(db, ann):
    txn = services.withdraw(db, ann, "120.50", now=NOON)
    assert services.get_balance(db, ann) == D("49879.50")
    assert (txn.kind, txn.amount, txn.balance_after) == (
        "withdrawal", D("120.50"), D("49879.50"))


def test_cannot_withdraw_more_than_balance(db):
    acct = services.open_account(db, "Bob", "1234")
    services.deposit(db, acct, "100")
    with pytest.raises(BankError, match="Insufficient funds"):
        services.withdraw(db, acct, "100.01", now=NOON)
    assert services.get_balance(db, acct) == D("100.00")


def test_can_withdraw_entire_balance(db):
    acct = services.open_account(db, "Bob", "1234")
    services.deposit(db, acct, "100")
    services.withdraw(db, acct, "100", now=NOON)
    assert services.get_balance(db, acct) == D("0.00")


def test_withdraw_from_empty_account(db):
    acct = services.open_account(db, "Bob", "1234")
    with pytest.raises(BankError, match="Insufficient funds"):
        services.withdraw(db, acct, "1", now=NOON)


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.234", None])
def test_bad_amounts_rejected(db, ann, bad):
    with pytest.raises(BankError):
        services.withdraw(db, ann, bad, now=NOON)
    assert services.get_balance(db, ann) == D("50000.00")


# -------------------------------------------------------------- daily limit

def test_exactly_the_limit_in_one_go_is_allowed(db, ann):
    services.withdraw(db, ann, "10000", now=NOON)


def test_one_cent_over_the_limit_is_rejected(db, ann):
    with pytest.raises(BankError, match="Daily limit"):
        services.withdraw(db, ann, "10000.01", now=NOON)
    assert services.get_balance(db, ann) == D("50000.00")


def test_limit_is_cumulative_across_withdrawals(db, ann):
    services.withdraw(db, ann, "6000", now=NOON)
    services.withdraw(db, ann, "4000", now=NOON + timedelta(hours=1))
    with pytest.raises(BankError, match="Daily limit"):
        services.withdraw(db, ann, "0.01", now=NOON + timedelta(hours=2))


def test_error_says_how_much_is_left(db, ann):
    services.withdraw(db, ann, "7500", now=NOON)
    with pytest.raises(BankError) as e:
        services.withdraw(db, ann, "3000", now=NOON)
    assert "$10,000.00" in str(e.value) and "$2,500.00" in str(e.value)


def test_rejected_attempts_do_not_count_towards_the_limit(db, ann):
    services.withdraw(db, ann, "6000", now=NOON)
    for _ in range(3):
        with pytest.raises(BankError):
            services.withdraw(db, ann, "5000", now=NOON)  # over the limit
    services.withdraw(db, ann, "4000", now=NOON)  # the full remainder still works


def test_insufficient_funds_attempts_do_not_count(db):
    acct = services.open_account(db, "Bob", "1234")
    services.deposit(db, acct, "100")
    with pytest.raises(BankError):
        services.withdraw(db, acct, "9000", now=NOON)
    assert services.sent_today(db, acct, NOON) == D("0")


def test_deposits_do_not_raise_the_limit(db, ann):
    services.withdraw(db, ann, "10000", now=NOON)
    services.deposit(db, ann, "5000")
    with pytest.raises(BankError, match="Daily limit"):
        services.withdraw(db, ann, "1", now=NOON)


def test_limit_is_per_account(db, ann):
    bob = services.open_account(db, "Bob", "1234")
    services.deposit(db, bob, "20000")
    services.withdraw(db, ann, "10000", now=NOON)
    services.withdraw(db, bob, "10000", now=NOON)  # unaffected by Ann


def test_transfer_out_counts_towards_the_limit(db, ann):
    """Step 5 will write 'transfer_out' rows; the limit must already include them."""
    ann = services._locked_account(db, ann)
    ann.balance -= D("9000")
    services._record(db, ann, "transfer_out", D("9000"), NOON)
    db.commit()
    with pytest.raises(BankError, match="Daily limit"):
        services.withdraw(db, ann, "1000.01", now=NOON)
    services.withdraw(db, ann, "1000", now=NOON)


# -------------------------------------------------- midnight reset (Sydney)

def test_limit_resets_at_local_midnight(db, ann):
    services.withdraw(db, ann, "10000", now=at(2026, 3, 10, 23, 59, 59))
    with pytest.raises(BankError):
        services.withdraw(db, ann, "1", now=at(2026, 3, 10, 23, 59, 59))
    services.withdraw(db, ann, "10000", now=at(2026, 3, 11, 0, 0, 0))


def test_withdrawal_just_after_midnight_belongs_to_the_new_day(db, ann):
    services.withdraw(db, ann, "10000", now=at(2026, 3, 10, 0, 0, 0))
    services.withdraw(db, ann, "10000", now=at(2026, 3, 9, 23, 59, 59))  # previous day


def test_reset_uses_local_time_not_utc(db, ann):
    # 10:30 UTC on 9 Mar is 21:30 Sydney (still the 9th); 13:30 UTC is 00:30 on the 10th.
    late_9th = datetime(2026, 3, 9, 10, 30, tzinfo=timezone.utc)
    early_10th = datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)
    services.withdraw(db, ann, "10000", now=late_9th)
    services.withdraw(db, ann, "10000", now=early_10th)


@pytest.mark.parametrize("day,hours", [
    ((2026, 3, 10), 24),   # ordinary day
    ((2026, 4, 5), 25),    # DST ends (clocks go back)
    ((2026, 10, 4), 23),   # DST starts (clocks go forward)
])
def test_day_bounds_handle_daylight_saving(day, hours):
    start, end = services.day_bounds(at(*day, 12))
    assert end - start == timedelta(hours=hours)
    assert start.astimezone(SYD).time().isoformat() == "00:00:00"
    assert end.astimezone(SYD).time().isoformat() == "00:00:00"


# ------------------------------------------------------------- concurrency

def test_concurrent_withdrawals_cannot_beat_the_limit(session_factory):
    with session_factory() as s:
        acct = services.open_account(s, "Ann", "1234")
        services.deposit(s, acct, "50000")
        acct_id = acct.id

    def attempt(_):
        with session_factory() as s:
            try:
                services.withdraw(s, s.get(Account, acct_id), "3000")
                return True
            except BankError:
                return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(10)))

    assert sum(results) == 3  # 3 x 3000 = 9000 fits; a 4th would make 12000
    with session_factory() as s:
        assert s.get(Account, acct_id).balance == D("41000.00")
        assert len(s.scalars(select(Transaction).where(
            Transaction.kind == "withdrawal")).all()) == 3
