import cli
from bankapp import config, services


def feed(monkeypatch, inputs, secrets):
    """Script the prompts: `inputs` for input(), `secrets` for getpass()."""
    inputs, secrets = iter(inputs), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))
    monkeypatch.setattr(cli, "getpass", lambda _="": next(secrets))


def wire(monkeypatch, session_factory):
    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    monkeypatch.setattr(cli, "init_db", lambda: None)


def test_cli_open_then_login(monkeypatch, session_factory, capsys):
    wire(monkeypatch, session_factory)
    feed(monkeypatch, ["Ann"], ["1234"])
    assert cli.main(["cli.py", "open"]) == 0
    number = capsys.readouterr().out.split("number is ")[1].strip(" .\n")

    feed(monkeypatch, [number, "6"], ["1234"])  # "6" = log out of the menu
    assert cli.main(["cli.py", "login"]) == 0
    assert "Welcome, Ann." in capsys.readouterr().out


def test_cli_login_wrong_pin(monkeypatch, session_factory, db, capsys):
    wire(monkeypatch, session_factory)
    ann = services.open_account(db, "Ann", "1234")
    feed(monkeypatch, [ann.number], ["0000"])
    assert cli.main(["cli.py", "login"]) == 1
    assert "Invalid account number or PIN" in capsys.readouterr().out


def test_cli_unlock_needs_admin_credentials(monkeypatch, session_factory, db, capsys):
    wire(monkeypatch, session_factory)
    monkeypatch.setattr(config, "ADMIN_USER", "admin")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "admin123")
    ann = services.open_account(db, "Ann", "1234")
    for _ in range(3):
        try:
            services.login(db, ann.number, "0000")
        except Exception:
            pass

    feed(monkeypatch, ["admin"], ["wrong"])
    assert cli.main(["cli.py", "unlock", ann.number]) == 1
    db.refresh(ann)
    assert ann.locked

    feed(monkeypatch, ["admin"], ["admin123"])
    assert cli.main(["cli.py", "unlock", ann.number]) == 0
    db.refresh(ann)
    assert not ann.locked


def test_cli_unlock_requires_account_number(monkeypatch, session_factory, capsys):
    wire(monkeypatch, session_factory)
    assert cli.main(["cli.py", "unlock"]) == 1
    assert "Usage" in capsys.readouterr().out


def test_cli_menu_balance_and_deposit(monkeypatch, session_factory, db, capsys):
    wire(monkeypatch, session_factory)
    ann = services.open_account(db, "Ann", "1234")
    # login -> balance, deposit 25.50, bad deposit, balance again, log out
    feed(monkeypatch, [ann.number, "1", "2", "25.50", "2", "-3", "1", "6"], ["1234"])
    assert cli.main(["cli.py", "login"]) == 0
    out = capsys.readouterr().out
    assert "Balance: $0.00" in out
    assert "Deposited $25.50. Balance: $25.50" in out
    assert "Error: Amount must be greater than zero." in out
    assert out.count("Balance: $25.50") == 2  # after-deposit line + final check


def test_cli_menu_withdraw(monkeypatch, session_factory, db, capsys):
    wire(monkeypatch, session_factory)
    ann = services.open_account(db, "Ann", "1234")
    services.deposit(db, ann, "100")
    # withdraw 30, then try to withdraw 500 (too much), log out
    feed(monkeypatch, [ann.number, "3", "30", "3", "500", "6"], ["1234"])
    assert cli.main(["cli.py", "login"]) == 0
    out = capsys.readouterr().out
    assert "Withdrew $30.00. Balance: $70.00" in out
    assert "Error: Insufficient funds." in out


def test_cli_menu_transfer(monkeypatch, session_factory, db, capsys):
    wire(monkeypatch, session_factory)
    ann = services.open_account(db, "Ann", "1234")
    bob = services.open_account(db, "Bob", "4321")
    services.deposit(db, ann, "100")
    # send 40 to Bob, try sending to a missing account, to herself, then log out
    feed(monkeypatch, [ann.number, "4", bob.number, "40", "4", "0000000000", "5",
                       "4", ann.number, "5", "6"], ["1234"])
    assert cli.main(["cli.py", "login"]) == 0
    out = capsys.readouterr().out
    assert f"Sent $40.00 to account {bob.number}. Balance: $60.00" in out
    assert "Error: Recipient account not found." in out
    assert "Error: You can't transfer to your own account." in out
    db.refresh(bob)
    assert str(bob.balance) == "40.00"
