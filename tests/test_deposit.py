from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import select

from bankapp import services
from bankapp.errors import BankError
from bankapp.models import Account, Transaction


@pytest.fixture
def ann(db):
    return services.open_account(db, "Ann", "1234")


@pytest.mark.parametrize("raw,expected", [
    ("10", "10.00"), ("10.5", "10.50"), (10.25, "10.25"), (Decimal("3.1"), "3.10"),
    (" 7 ", "7.00"), (1, "1.00"), ("0.01", "0.01"),
])
def test_parse_amount_accepts(raw, expected):
    assert services.parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [
    0, "0", "-5", -0.01, "abc", "", None, True, "1.234", "nan", "inf", "-inf",
    "1e3x", "99999999999",
])
def test_parse_amount_rejects(raw):
    with pytest.raises(BankError):
        services.parse_amount(raw)


def test_new_account_has_zero_balance(db, ann):
    assert services.get_balance(db, ann) == Decimal("0.00")


def test_deposit_increases_balance_and_records_transaction(db, ann):
    txn = services.deposit(db, ann, "100.50")
    assert services.get_balance(db, ann) == Decimal("100.50")
    assert (txn.kind, txn.amount, txn.balance_after) == (
        "deposit", Decimal("100.50"), Decimal("100.50"))
    assert txn.account_id == ann.id and txn.created_at is not None


def test_deposits_accumulate_without_float_error(db, ann):
    services.deposit(db, ann, "0.10")
    services.deposit(db, ann, "0.20")
    assert services.get_balance(db, ann) == Decimal("0.30")
    rows = db.scalars(select(Transaction).order_by(Transaction.id)).all()
    assert [r.balance_after for r in rows] == [Decimal("0.10"), Decimal("0.30")]


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.001"])
def test_rejected_deposit_changes_nothing(db, ann, bad):
    with pytest.raises(BankError):
        services.deposit(db, ann, bad)
    assert services.get_balance(db, ann) == Decimal("0.00")
    assert db.scalars(select(Transaction)).all() == []


def test_deposit_cannot_exceed_max_balance(db, ann):
    services.deposit(db, ann, services.MAX_BALANCE)
    with pytest.raises(BankError):
        services.deposit(db, ann, "0.01")
    assert services.get_balance(db, ann) == services.MAX_BALANCE
    assert len(db.scalars(select(Transaction)).all()) == 1


def test_balances_are_per_account(db, ann):
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "50")
    assert services.get_balance(db, bob) == Decimal("0.00")


def test_concurrent_deposits_do_not_lose_updates(session_factory):
    with session_factory() as s:
        acct_id = services.open_account(s, "Ann", "1234").id

    def one_deposit(_):
        with session_factory() as s:
            services.deposit(s, s.get(Account, acct_id), "1")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one_deposit, range(20)))

    with session_factory() as s:
        assert s.get(Account, acct_id).balance == Decimal("20.00")
        assert len(s.scalars(select(Transaction)).all()) == 20
