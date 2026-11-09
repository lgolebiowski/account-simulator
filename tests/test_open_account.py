import pytest
from sqlalchemy import select

from bankapp import services
from bankapp.errors import BankError
from bankapp.models import Account
from bankapp.security import verify_pin


def test_open_account_creates_zero_balance_account(db):
    acct = services.open_account(db, "Ann", "1234")
    assert len(acct.number) == 10 and acct.number.isdigit()
    assert acct.owner == "Ann"
    assert str(acct.balance) == "0.00"
    assert acct.locked is False and acct.failed_attempts == 0


def test_pin_is_stored_hashed(db):
    acct = services.open_account(db, "Ann", "1234")
    assert "1234" not in acct.pin_hash
    assert verify_pin("1234", acct.pin_hash)
    assert not verify_pin("0000", acct.pin_hash)


def test_account_numbers_are_unique(db):
    a = services.open_account(db, "Ann", "1234")
    b = services.open_account(db, "Bob", "1234")
    assert a.number != b.number


@pytest.mark.parametrize("pin", ["123", "12345", "abcd", "12 4", "", "١٢٣٤"])
def test_bad_pin_rejected(db, pin):
    with pytest.raises(BankError):
        services.open_account(db, "Ann", pin)
    assert db.scalars(select(Account)).all() == []


@pytest.mark.parametrize("owner", ["", "   "])
def test_blank_owner_rejected(db, owner):
    with pytest.raises(BankError):
        services.open_account(db, owner, "1234")


def test_api_open_account(client):
    r = client.post("/accounts", json={"owner": "Ann", "pin": "1234"})
    assert r.status_code == 201
    body = r.json()
    assert body["owner"] == "Ann" and len(body["number"]) == 10
    assert "pin" not in body and "pin_hash" not in body


def test_api_bad_pin_returns_400(client):
    r = client.post("/accounts", json={"owner": "Ann", "pin": "12"})
    assert r.status_code == 400
    assert "PIN" in r.json()["detail"]
