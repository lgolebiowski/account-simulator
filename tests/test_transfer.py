from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from bankapp import config, services
from bankapp.db import init_db
from bankapp.errors import BankError
from bankapp.models import Account, Transaction

D = Decimal
NOON = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("Australia/Sydney"))


@pytest.fixture(autouse=True)
def sydney(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Australia/Sydney")
    # These tests probe the midnight limit reset, so open the bank 24h (hours have their own tests).
    monkeypatch.setattr(config, "OPEN_HOUR", 0)
    monkeypatch.setattr(config, "CLOSE_HOUR", 24)


@pytest.fixture
def pair(db):
    ann = services.open_account(db, "Ann", "1234")
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "50000")
    return ann, bob


def bal(db, acct):
    return services.get_balance(db, acct)


# ------------------------------------------------------------- happy path

def test_transfer_moves_money(db, pair):
    ann, bob = pair
    services.transfer(db, ann, bob.number, "1200.50", now=NOON)
    assert bal(db, ann) == D("48799.50") and bal(db, bob) == D("1200.50")


def test_transfer_writes_two_ledger_rows_with_counterparties(db, pair):
    ann, bob = pair
    out = services.transfer(db, ann, bob.number, "300", now=NOON)
    assert (out.kind, out.amount, out.balance_after, out.counterparty) == (
        "transfer_out", D("300.00"), D("49700.00"), bob.number)
    inn = db.scalar(select(Transaction).where(Transaction.kind == "transfer_in"))
    assert (inn.account_id, inn.amount, inn.balance_after, inn.counterparty) == (
        bob.id, D("300.00"), D("300.00"), ann.number)


def test_can_send_the_entire_balance(db):
    ann = services.open_account(db, "Ann", "1234")
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "75")
    services.transfer(db, ann, bob.number, "75", now=NOON)
    assert bal(db, ann) == D("0.00") and bal(db, bob) == D("75.00")


def test_recipient_number_is_trimmed(db, pair):
    ann, bob = pair
    services.transfer(db, ann, f"  {bob.number} ", "5", now=NOON)
    assert bal(db, bob) == D("5.00")


# ------------------------------------------------------------ rejections

def assert_nothing_changed(db, ann, bob):
    assert bal(db, ann) == D("50000.00") and bal(db, bob) == D("0.00")
    kinds = [t.kind for t in db.scalars(select(Transaction))]
    assert kinds == ["deposit"]


def test_insufficient_funds(db, pair):
    ann, bob = pair
    with pytest.raises(BankError, match="Insufficient funds"):
        services.transfer(db, bob, ann.number, "0.01", now=NOON)
    assert bal(db, bob) == D("0.00") and bal(db, ann) == D("50000.00")


def test_unknown_recipient(db, pair):
    ann, bob = pair
    with pytest.raises(BankError, match="Recipient account not found"):
        services.transfer(db, ann, "0000000000", "10", now=NOON)
    assert_nothing_changed(db, ann, bob)


def test_cannot_transfer_to_yourself(db, pair):
    ann, bob = pair
    with pytest.raises(BankError, match="own account"):
        services.transfer(db, ann, ann.number, "10", now=NOON)
    assert_nothing_changed(db, ann, bob)


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.234", None])
def test_bad_amounts(db, pair, bad):
    ann, bob = pair
    with pytest.raises(BankError):
        services.transfer(db, ann, bob.number, bad, now=NOON)
    assert_nothing_changed(db, ann, bob)


def test_recipient_cap_rejects_and_leaves_both_untouched(db, pair):
    ann, bob = pair
    services.deposit(db, bob, services.MAX_BALANCE)
    with pytest.raises(BankError, match="can't receive"):
        services.transfer(db, ann, bob.number, "1", now=NOON)
    assert bal(db, ann) == D("50000.00") and bal(db, bob) == services.MAX_BALANCE
    assert "transfer_out" not in [t.kind for t in db.scalars(select(Transaction))]


def test_locked_recipient_can_still_receive(db, pair):
    ann, bob = pair
    for _ in range(3):
        with pytest.raises(BankError):
            services.login(db, bob.number, "0000")
    db.refresh(bob)
    assert bob.locked
    services.transfer(db, ann, bob.number, "10", now=NOON)
    assert bal(db, bob) == D("10.00")


# ------------------------------------------------- shared daily limit

def test_transfers_and_withdrawals_share_one_daily_limit(db, pair):
    ann, bob = pair
    services.transfer(db, ann, bob.number, "6000", now=NOON)
    services.withdraw(db, ann, "4000", now=NOON)
    with pytest.raises(BankError, match="Daily limit"):
        services.transfer(db, ann, bob.number, "0.01", now=NOON)
    with pytest.raises(BankError, match="Daily limit"):
        services.withdraw(db, ann, "0.01", now=NOON)


def test_withdrawal_first_then_transfer_hits_the_limit(db, pair):
    ann, bob = pair
    services.withdraw(db, ann, "9000", now=NOON)
    with pytest.raises(BankError, match="You can still send \\$1,000.00"):
        services.transfer(db, ann, bob.number, "1000.01", now=NOON)
    services.transfer(db, ann, bob.number, "1000", now=NOON)


def test_receiving_money_does_not_use_up_your_limit(db, pair):
    ann, bob = pair
    services.transfer(db, ann, bob.number, "10000", now=NOON)
    services.withdraw(db, bob, "10000", now=NOON)  # Bob's own limit is untouched


def test_rejected_transfer_does_not_count(db, pair):
    ann, bob = pair
    with pytest.raises(BankError):
        services.transfer(db, ann, bob.number, "10001", now=NOON)
    services.transfer(db, ann, bob.number, "10000", now=NOON)


def test_transfer_limit_resets_at_midnight(db, pair):
    ann, bob = pair
    services.transfer(db, ann, bob.number, "10000", now=NOON)
    next_day = NOON.replace(day=11, hour=0, minute=0)
    services.transfer(db, ann, bob.number, "10000", now=next_day)


# ------------------------------------------------------------ concurrency

def test_opposite_transfers_at_once_do_not_deadlock_or_lose_money(session_factory):
    with session_factory() as s:
        a = services.open_account(s, "Ann", "1234")
        b = services.open_account(s, "Bob", "4321")
        services.deposit(s, a, "1000")
        services.deposit(s, b, "1000")
        a_id, b_id, a_no, b_no = a.id, b.id, a.number, b.number

    def go(i):
        with session_factory() as s:
            src, dst = (a_id, b_no) if i % 2 == 0 else (b_id, a_no)
            services.transfer(s, s.get(Account, src), dst, "10")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(go, range(40)))  # an exception here would mean a deadlock

    with session_factory() as s:
        total = sum(x.balance for x in s.scalars(select(Account)))
        assert total == D("2000.00")                    # nothing created or destroyed
        assert s.get(Account, a_id).balance == D("1000.00")  # 20 each way cancels out


def test_concurrent_transfers_cannot_beat_the_limit(session_factory):
    with session_factory() as s:
        a = services.open_account(s, "Ann", "1234")
        b = services.open_account(s, "Bob", "4321")
        services.deposit(s, a, "50000")
        a_id, b_no, b_id = a.id, b.number, b.id

    def attempt(_):
        with session_factory() as s:
            try:
                services.transfer(s, s.get(Account, a_id), b_no, "3000")
                return True
            except BankError:
                return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(10)))

    assert sum(results) == 3
    with session_factory() as s:
        assert s.get(Account, a_id).balance == D("41000.00")
        assert s.get(Account, b_id).balance == D("9000.00")


# -------------------------------------------------------------- database

def test_init_db_adds_counterparty_to_an_older_transactions_table(engine, session_factory):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transactions DROP COLUMN counterparty"))
    init_db(engine)
    init_db(engine)  # and it is safe to run twice
    with engine.connect() as conn:
        cols = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='transactions'")).scalars().all()
    assert "counterparty" in cols
