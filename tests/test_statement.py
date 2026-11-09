import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

import cli
from bankapp import config, services, statements
from bankapp.errors import BankError
from bankapp.models import Transaction

SYD = ZoneInfo("Australia/Sydney")
D = Decimal
TODAY = date(2026, 3, 10)  # the fixed test clock's date (a Tuesday)


@pytest.fixture(autouse=True)
def sydney(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Australia/Sydney")


def at(y, mo, d, h=12, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=SYD)


def add(db, acct, kind, amount, when, balance="0", other=None):
    """Insert a ledger row directly, at any time (bypasses office hours and balances)."""
    db.add(Transaction(account_id=acct.id, kind=kind, amount=D(amount), created_at=when,
                       balance_after=D(balance), counterparty=other))
    db.commit()


@pytest.fixture
def ann(db):
    return services.open_account(db, "Ann", "1234")


def lines(db, acct, start=None, end=None):
    return statements.get_statement(db, acct, start, end).lines


# ------------------------------------------------------------------ range

def test_default_range_is_the_last_30_days_ending_today(db, ann):
    add(db, ann, "deposit", "1", at(2026, 2, 8, 23, 59))   # day -30: outside
    add(db, ann, "deposit", "2", at(2026, 2, 9, 0, 0))     # day -29: first day inside
    add(db, ann, "deposit", "3", at(2026, 3, 10, 23, 59))  # today
    add(db, ann, "deposit", "4", at(2026, 3, 11, 0, 0))    # tomorrow: outside
    st = statements.get_statement(db, ann)
    assert (st.start, st.end) == (date(2026, 2, 9), TODAY)
    assert [l.amount for l in st.lines] == [D("2"), D("3")]


def test_range_is_inclusive_at_both_ends_to_the_second(db, ann):
    add(db, ann, "deposit", "1", at(2026, 3, 4, 23, 59, 59))  # before start
    add(db, ann, "deposit", "2", at(2026, 3, 5, 0, 0, 0))     # start, first second
    add(db, ann, "deposit", "3", at(2026, 3, 6, 23, 59, 59))  # end, last second
    add(db, ann, "deposit", "4", at(2026, 3, 7, 0, 0, 0))     # after end
    got = lines(db, ann, date(2026, 3, 5), date(2026, 3, 6))
    assert [l.amount for l in got] == [D("2"), D("3")]


def test_days_are_sydney_days_not_utc_days(db, ann):
    # 14:00 UTC on 9 March is 01:00 on 10 March in Sydney (UTC+11).
    add(db, ann, "deposit", "7", datetime(2026, 3, 9, 14, 0, tzinfo=timezone.utc))
    assert lines(db, ann, date(2026, 3, 9), date(2026, 3, 9)) == []
    got = lines(db, ann, date(2026, 3, 10), date(2026, 3, 10))
    assert len(got) == 1 and got[0].time.hour == 1 and got[0].time.day == 10


def test_a_25_hour_daylight_saving_day_is_fully_covered(db, ann):
    add(db, ann, "deposit", "5", at(2026, 4, 5, 23, 30))  # DST ends on 5 April 2026
    assert len(lines(db, ann, date(2026, 4, 5), date(2026, 4, 5))) == 1
    assert lines(db, ann, date(2026, 4, 6), date(2026, 4, 6)) == []


def test_only_end_given_uses_30_days_before_it(db, ann):
    st = statements.get_statement(db, ann, None, date(2026, 1, 31))
    assert (st.start, st.end) == (date(2026, 1, 2), date(2026, 1, 31))


def test_only_start_given_runs_to_today(db, ann):
    st = statements.get_statement(db, ann, date(2026, 3, 1), None)
    assert (st.start, st.end) == (date(2026, 3, 1), TODAY)


def test_one_day_range(db, ann):
    st = statements.get_statement(db, ann, TODAY, TODAY)
    assert st.start == st.end == TODAY


def test_start_after_end_is_rejected(db, ann):
    with pytest.raises(BankError, match="start date"):
        statements.get_statement(db, ann, date(2026, 3, 9), date(2026, 3, 8))
    with pytest.raises(BankError):  # a start date in the future gives start > today
        statements.get_statement(db, ann, date(2026, 12, 1), None)


def test_empty_period(db, ann):
    assert lines(db, ann) == []


# ---------------------------------------------------------------- content

def test_signs_labels_counterparties_and_balances(db, ann):
    add(db, ann, "deposit", "500", at(2026, 3, 2), "500")
    add(db, ann, "withdrawal", "100", at(2026, 3, 3), "400")
    add(db, ann, "transfer_out", "50", at(2026, 3, 4), "350", other="1111111111")
    add(db, ann, "transfer_in", "25", at(2026, 3, 5), "375", other="2222222222")
    got = lines(db, ann)
    assert [(l.type, l.amount, l.other_account, l.balance) for l in got] == [
        ("Deposit", D("500"), None, D("500")),
        ("Withdrawal", D("-100"), None, D("400")),
        ("Transfer out", D("-50"), "1111111111", D("350")),
        ("Transfer in", D("25"), "2222222222", D("375")),
    ]


def test_oldest_first_with_insertion_order_breaking_ties(db, ann):
    t = at(2026, 3, 5)
    add(db, ann, "deposit", "3", at(2026, 3, 6))
    add(db, ann, "deposit", "1", t)
    add(db, ann, "deposit", "2", t)
    assert [l.amount for l in lines(db, ann)] == [D("1"), D("2"), D("3")]


def test_each_account_sees_only_its_own_lines(db, ann):
    bob = services.open_account(db, "Bob", "4321")
    add(db, ann, "deposit", "1", at(2026, 3, 5))
    add(db, bob, "deposit", "2", at(2026, 3, 5))
    assert [l.amount for l in lines(db, ann)] == [D("1")]
    assert [l.amount for l in lines(db, bob)] == [D("2")]


def test_statement_reflects_real_operations(db, ann):
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "1000")
    services.withdraw(db, ann, "200.50")
    services.transfer(db, ann, bob.number, "300")
    a, b = lines(db, ann), lines(db, bob)
    assert [(l.type, l.amount, l.balance) for l in a] == [
        ("Deposit", D("1000.00"), D("1000.00")),
        ("Withdrawal", D("-200.50"), D("799.50")),
        ("Transfer out", D("-300.00"), D("499.50")),
    ]
    assert a[2].other_account == bob.number
    assert [(l.type, l.amount, l.other_account) for l in b] == [
        ("Transfer in", D("300.00"), ann.number)]
    assert a[0].time == at(2026, 3, 10, 12)  # stamped with the (fixed) banking clock


def test_statements_work_when_the_bank_is_closed(db, ann, set_clock):
    services.deposit(db, ann, "10")
    set_clock(at(2026, 3, 15, 12))  # Sunday
    assert len(lines(db, ann, date(2026, 3, 1), date(2026, 3, 15))) == 1


# -------------------------------------------------------------------- csv

def parse(text):
    return list(csv.reader(io.StringIO(text)))


def test_csv_layout_and_signed_plain_numbers(db, ann):
    add(db, ann, "deposit", "1234.5", at(2026, 3, 2, 9, 5, 7), "1234.50")
    add(db, ann, "transfer_out", "250", at(2026, 3, 3, 15, 0, 0), "984.50", other="1111111111")
    rows = parse(statements.to_csv(statements.get_statement(db, ann)))
    assert rows == [
        ["Date", "Time", "Type", "Other account", "Amount", "Balance"],
        ["2026-03-02", "09:05:07", "Deposit", "", "1234.50", "1234.50"],
        ["2026-03-03", "15:00:00", "Transfer out", "1111111111", "-250.00", "984.50"],
    ]


def test_csv_of_an_empty_period_is_just_the_header(db, ann):
    text = statements.to_csv(statements.get_statement(db, ann))
    assert parse(text) == [statements.CSV_HEADER]


def test_csv_uses_crlf_line_endings_and_no_thousands_separators(db, ann):
    add(db, ann, "deposit", "1234567.89", at(2026, 3, 2), "1234567.89")
    text = statements.to_csv(statements.get_statement(db, ann))
    assert text.endswith("\r\n") and "1234567.89" in text and "1,234" not in text


def test_csv_contains_no_user_typed_text(db):
    evil = services.open_account(db, "=HYPERLINK(\"x\"),\"; DROP", "1234")
    services.deposit(db, evil, "5")
    text = statements.to_csv(statements.get_statement(db, evil))
    assert "HYPERLINK" not in text and "DROP" not in text


# -------------------------------------------------------------------- API

def auth(token):
    return {"Authorization": f"Bearer {token}"}


def logged_in(client, owner="Ann", pin="1234"):
    number = client.post("/accounts", json={"owner": owner, "pin": pin}).json()["number"]
    token = client.post("/login", json={"number": number, "pin": pin}).json()["token"]
    return number, auth(token)


def test_api_statement_default_range(client):
    number, h = logged_in(client)
    client.post("/deposit", json={"amount": "100"}, headers=h)
    client.post("/withdraw", json={"amount": "40.25"}, headers=h)
    r = client.get("/statement", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert (body["start"], body["end"], body["timezone"]) == (
        "2026-02-09", "2026-03-10", "Australia/Sydney")
    assert [(t["type"], t["amount"], t["balance"]) for t in body["transactions"]] == [
        ("Deposit", "100.00", "100.00"), ("Withdrawal", "-40.25", "59.75")]
    assert body["transactions"][0]["time"] == "2026-03-10T12:00:00+11:00"
    assert body["transactions"][0]["other_account"] is None


def test_api_statement_with_a_range(client):
    _, h = logged_in(client)
    client.post("/deposit", json={"amount": "100"}, headers=h)
    r = client.get("/statement?start=2026-03-01&end=2026-03-09", headers=h)
    assert r.json()["transactions"] == []
    r = client.get("/statement?start=2026-03-10&end=2026-03-10", headers=h)
    assert len(r.json()["transactions"]) == 1


def test_api_statement_errors(client):
    _, h = logged_in(client)
    assert client.get("/statement?start=2026-03-09&end=2026-03-01", headers=h).status_code == 400
    assert client.get("/statement?start=not-a-date", headers=h).status_code == 422
    assert client.get("/statement?end=2026-13-45", headers=h).status_code == 422
    assert client.get("/statement.csv?start=2026-03-09&end=2026-03-01", headers=h).status_code == 400


def test_api_statement_requires_login(client):
    assert client.get("/statement").status_code == 401
    assert client.get("/statement.csv").status_code == 401
    assert client.get("/statement", headers=auth("junk")).status_code == 401


def test_api_transfer_shows_on_both_statements(client):
    ann_no, ann = logged_in(client, "Ann", "1234")
    bob_no, bob = logged_in(client, "Bob", "4321")
    client.post("/deposit", json={"amount": "100"}, headers=ann)
    client.post("/transfer", json={"to": bob_no, "amount": "30"}, headers=ann)
    a = client.get("/statement", headers=ann).json()["transactions"][-1]
    b = client.get("/statement", headers=bob).json()["transactions"][-1]
    assert (a["type"], a["amount"], a["other_account"]) == ("Transfer out", "-30.00", bob_no)
    assert (b["type"], b["amount"], b["other_account"]) == ("Transfer in", "30.00", ann_no)


def test_api_csv_download(client):
    number, h = logged_in(client)
    client.post("/deposit", json={"amount": "100"}, headers=h)
    client.post("/withdraw", json={"amount": "40.25"}, headers=h)
    r = client.get("/statement.csv?start=2026-03-01&end=2026-03-31", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == (
        f'attachment; filename="statement-{number}-2026-03-01-to-2026-03-31.csv"')
    assert parse(r.text) == [
        ["Date", "Time", "Type", "Other account", "Amount", "Balance"],
        ["2026-03-10", "12:00:00", "Deposit", "", "100.00", "100.00"],
        ["2026-03-10", "12:00:00", "Withdrawal", "", "-40.25", "59.75"],
    ]


def test_api_csv_matches_the_json_statement(client):
    _, h = logged_in(client)
    for amount in ("10", "20", "30"):
        client.post("/deposit", json={"amount": amount}, headers=h)
    js = client.get("/statement", headers=h).json()["transactions"]
    rows = parse(client.get("/statement.csv", headers=h).text)[1:]
    assert [r[4] for r in rows] == [t["amount"] for t in js]


def test_api_statements_are_private_to_each_user(client):
    _, ann = logged_in(client, "Ann", "1234")
    _, bob = logged_in(client, "Bob", "4321")
    client.post("/deposit", json={"amount": "100"}, headers=ann)
    assert client.get("/statement", headers=bob).json()["transactions"] == []
    assert parse(client.get("/statement.csv", headers=bob).text) == [statements.CSV_HEADER]


def test_api_statement_works_when_the_bank_is_closed(client, set_clock):
    _, h = logged_in(client)
    client.post("/deposit", json={"amount": "100"}, headers=h)
    set_clock(at(2026, 3, 15, 12))  # Sunday
    assert client.get("/statement", headers=h).status_code == 200
    assert client.get("/statement.csv", headers=h).status_code == 200


# -------------------------------------------------------------------- CLI

def feed(monkeypatch, inputs, secrets):
    inputs, secrets = iter(inputs), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr(cli, "getpass", lambda _="": next(secrets))


@pytest.fixture
def wired(monkeypatch, session_factory):
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(cli, "init_db", lambda: None)


def test_cli_statement_prints_only_the_last_10_lines(wired, monkeypatch, db, capsys):
    ann = services.open_account(db, "Ann", "1234")
    for i in range(12):  # 12 deposits on consecutive days, the newest being today (10 March)
        add(db, ann, "deposit", str(i + 1), at(2026, 3, 10) - timedelta(days=i), "0")
    # menu 5, from blank, to blank, no file, log out
    feed(monkeypatch, [ann.number, "5", "", "", "", "6"], ["1234"])
    assert cli.main(["cli.py", "login"]) == 0
    out = capsys.readouterr().out
    assert "showing the last 10 of 12" in out
    assert "2026-03-10 12:00" in out and "2026-03-01 12:00" in out
    assert "2026-02-28 12:00" not in out and "2026-02-27 12:00" not in out  # the 2 oldest are cut


def test_cli_statement_saves_a_csv(wired, monkeypatch, db, capsys, tmp_path):
    ann = services.open_account(db, "Ann", "1234")
    services.deposit(db, ann, "100")
    target = tmp_path / "out.csv"
    feed(monkeypatch, [ann.number, "5", "2026-03-01", "2026-03-31", str(target), "6"], ["1234"])
    assert cli.main(["cli.py", "login"]) == 0
    assert "Saved 1 lines" in capsys.readouterr().out
    assert parse(target.read_text())[1] == [
        "2026-03-10", "12:00:00", "Deposit", "", "100.00", "100.00"]


def test_cli_statement_never_overwrites_a_file(wired, monkeypatch, db, capsys, tmp_path):
    ann = services.open_account(db, "Ann", "1234")
    target = tmp_path / "keep.csv"
    target.write_text("precious")
    feed(monkeypatch, [ann.number, "5", "", "", str(target), "6"], ["1234"])
    cli.main(["cli.py", "login"])
    assert "Couldn't save the file" in capsys.readouterr().out
    assert target.read_text() == "precious"


def test_cli_statement_bad_dates(wired, monkeypatch, db, capsys):
    ann = services.open_account(db, "Ann", "1234")
    feed(monkeypatch, [ann.number, "5", "31/03/2026", "6"], ["1234"])
    cli.main(["cli.py", "login"])
    assert "Dates must look like 2026-03-31." in capsys.readouterr().out
    feed(monkeypatch, [ann.number, "5", "2026-03-09", "2026-03-01", "6"], ["1234"])
    cli.main(["cli.py", "login"])
    assert "start date must be on or before" in capsys.readouterr().out


def test_cli_statement_empty_period(wired, monkeypatch, db, capsys):
    ann = services.open_account(db, "Ann", "1234")
    feed(monkeypatch, [ann.number, "5", "", "", "", "6"], ["1234"])
    cli.main(["cli.py", "login"])
    assert "No transactions in this period." in capsys.readouterr().out
