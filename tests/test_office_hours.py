from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import cli
from bankapp import config, services
from bankapp.errors import BankError, ClosedError
from bankapp.models import Transaction

SYD = ZoneInfo("Australia/Sydney")
CLOSED_TEXT = ("The bank is closed. Transactions are available "
               "Monday–Friday, 8am–5pm (Sydney time).")


def at(y, mo, d, h=12, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=SYD)


# 2026-03-09 is a Monday ... 2026-03-13 Friday, 14 Saturday, 15 Sunday.
@pytest.mark.parametrize("when,expected", [
    (at(2026, 3, 9, 8, 0, 0), True),      # Monday, opening moment
    (at(2026, 3, 9, 7, 59, 59), False),   # one second before opening
    (at(2026, 3, 10, 12), True),
    (at(2026, 3, 13, 16, 59, 59), True),  # Friday, last second
    (at(2026, 3, 13, 17, 0, 0), False),   # 17:00 sharp is closed
    (at(2026, 3, 13, 17, 0, 1), False),
    (at(2026, 3, 9, 0, 0, 0), False),     # midnight
    (at(2026, 3, 14, 12), False),         # Saturday noon
    (at(2026, 3, 15, 12), False),         # Sunday noon
    (at(2026, 3, 14, 9), False),
])
def test_is_open(when, expected):
    assert services.is_open(when) is expected


def test_hours_are_judged_in_sydney_time_not_utc():
    # Monday 22:00 UTC is already Tuesday 09:00 in Sydney (AEDT, UTC+11): open.
    assert services.is_open(datetime(2026, 3, 9, 22, 0, tzinfo=timezone.utc))
    # Friday 07:00 UTC is Friday 18:00 in Sydney: closed.
    assert not services.is_open(datetime(2026, 3, 13, 7, 0, tzinfo=timezone.utc))
    # Sunday 22:30 UTC is Monday 09:30 Sydney: open, although it is Sunday in UTC.
    assert services.is_open(datetime(2026, 3, 15, 22, 30, tzinfo=timezone.utc))


def test_hours_follow_daylight_saving():
    # After DST ends (5 Apr 2026) Sydney is UTC+10: 07:30 UTC Mon 6 Apr = 17:30 local, closed.
    assert not services.is_open(datetime(2026, 4, 6, 7, 30, tzinfo=timezone.utc))
    # Before it ends (UTC+11), 06:30 UTC Mon 30 Mar = 17:30 local: also closed...
    assert not services.is_open(datetime(2026, 3, 30, 6, 30, tzinfo=timezone.utc))
    # ...but 05:30 UTC then is 16:30 local: open.
    assert services.is_open(datetime(2026, 3, 30, 5, 30, tzinfo=timezone.utc))


def test_closed_message_text():
    assert services.closed_message() == CLOSED_TEXT


def test_hours_can_be_changed_via_config(monkeypatch):
    monkeypatch.setattr(config, "OPEN_HOUR", 9)
    monkeypatch.setattr(config, "CLOSE_HOUR", 13)
    assert services.is_open(at(2026, 3, 10, 12, 59))
    assert not services.is_open(at(2026, 3, 10, 13, 0))
    assert "9am–1pm" in services.closed_message()


# ------------------------------------------------ services refuse when closed

@pytest.fixture
def pair(db):
    ann = services.open_account(db, "Ann", "1234")
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "500")  # made at the fixed (open) test time
    return ann, bob


SUNDAY = at(2026, 3, 15, 12)
AFTER_FIVE = at(2026, 3, 10, 17, 0, 0)


@pytest.mark.parametrize("closed", [SUNDAY, AFTER_FIVE, at(2026, 3, 10, 7, 59, 59)])
def test_deposit_withdraw_transfer_all_refused_when_closed(db, pair, set_clock, closed):
    ann, bob = pair
    set_clock(closed)
    for action in (lambda: services.deposit(db, ann, "10"),
                   lambda: services.withdraw(db, ann, "10"),
                   lambda: services.transfer(db, ann, bob.number, "10")):
        with pytest.raises(ClosedError) as e:
            action()
        assert str(e.value) == CLOSED_TEXT
    assert services.get_balance(db, ann) == Decimal("500.00")
    assert services.get_balance(db, bob) == Decimal("0.00")
    assert [t.kind for t in db.scalars(select(Transaction))] == ["deposit"]


def test_closed_takes_priority_over_other_errors(db, pair, set_clock):
    ann, bob = pair
    set_clock(SUNDAY)
    with pytest.raises(ClosedError):
        services.withdraw(db, ann, "99999999")       # would be insufficient funds
    with pytest.raises(ClosedError):
        services.deposit(db, ann, "abc")             # would be an invalid amount
    with pytest.raises(ClosedError):
        services.transfer(db, ann, "0000000000", "5")  # would be unknown recipient


def test_moves_resume_when_the_bank_opens(db, pair, set_clock):
    ann, bob = pair
    set_clock(at(2026, 3, 10, 16, 59, 59))
    services.withdraw(db, ann, "10")
    set_clock(at(2026, 3, 10, 17, 0, 0))
    with pytest.raises(ClosedError):
        services.withdraw(db, ann, "10")
    set_clock(at(2026, 3, 11, 8, 0, 0))
    services.withdraw(db, ann, "10")


def test_refused_attempts_do_not_use_the_daily_limit(db, pair, set_clock):
    ann, bob = pair
    set_clock(SUNDAY)
    for _ in range(3):
        with pytest.raises(ClosedError):
            services.withdraw(db, ann, "400")
    assert services.sent_today(db, ann, SUNDAY) == Decimal("0")


def test_closed_error_is_a_bank_error():
    assert issubclass(ClosedError, BankError) and ClosedError.status_code == 403


# ------------------------------------------- things that stay open after hours

def test_login_balance_and_unlock_work_when_closed(db, pair, set_clock):
    ann, bob = pair
    set_clock(SUNDAY)
    token = services.login(db, ann.number, "1234")
    assert services.account_for_token(db, token).id == ann.id
    assert services.get_balance(db, ann) == Decimal("500.00")
    services.open_account(db, "Cy", "1111")
    services.unlock_account(db, ann.number)


# ----------------------------------------------------------------------- API

def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_returns_403_with_message_for_every_money_endpoint_when_closed(client, set_clock):
    set_clock(at(2026, 3, 10, 12))  # open, so setup works
    ann_no = client.post("/accounts", json={"owner": "Ann", "pin": "1234"}).json()["number"]
    bob_no = client.post("/accounts", json={"owner": "Bob", "pin": "4321"}).json()["number"]
    h = auth(client.post("/login", json={"number": ann_no, "pin": "1234"}).json()["token"])
    client.post("/deposit", json={"amount": "100"}, headers=h)

    set_clock(SUNDAY)
    for path, body in [("/deposit", {"amount": "5"}), ("/withdraw", {"amount": "5"}),
                       ("/transfer", {"to": bob_no, "amount": "5"})]:
        r = client.post(path, json=body, headers=h)
        assert r.status_code == 403, path
        assert r.json()["detail"] == CLOSED_TEXT
    # read-only endpoints still work, and nothing moved
    assert client.get("/balance", headers=h).json() == {"balance": "100.00"}
    assert client.get("/me", headers=h).status_code == 200
    # a fresh login works after hours too
    assert client.post("/login", json={"number": ann_no, "pin": "1234"}).status_code == 200


def test_api_money_works_again_when_open(client, set_clock):
    set_clock(SUNDAY)
    no = client.post("/accounts", json={"owner": "Ann", "pin": "1234"}).json()["number"]
    h = auth(client.post("/login", json={"number": no, "pin": "1234"}).json()["token"])
    assert client.post("/deposit", json={"amount": "5"}, headers=h).status_code == 403
    set_clock(at(2026, 3, 16, 9))  # Monday morning
    assert client.post("/deposit", json={"amount": "5"}, headers=h).status_code == 200


# ----------------------------------------------------------------------- CLI

def test_cli_shows_the_closed_message(monkeypatch, session_factory, db, set_clock, capsys):
    ann = services.open_account(db, "Ann", "1234")
    set_clock(SUNDAY)
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    inputs = iter([ann.number, "2", "10", "6"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr(cli, "getpass", lambda _="": "1234")
    assert cli.main(["cli.py", "login"]) == 0
    assert f"Error: {CLOSED_TEXT}" in capsys.readouterr().out
