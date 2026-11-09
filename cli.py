"""Command-line interface.

Usage:
    python cli.py open              open a new account
    python cli.py login             log in, then check balance / deposit / withdraw / transfer / statement from a menu
    python cli.py unlock <number>   unlock an account (asks for admin credentials)
"""
import sys
from datetime import date
from getpass import getpass

from bankapp import services, statements
from bankapp.db import SessionLocal, init_db
from bankapp.errors import BankError


def cmd_open(args):
    owner = input("Your name: ")
    pin = getpass("Choose a 4-digit PIN: ")
    with SessionLocal() as db:
        account = services.open_account(db, owner, pin)
    print(f"Account created. Your account number is {account.number}.")


MENU = """
1) Check balance
2) Deposit
3) Withdraw
4) Transfer
5) Statement
6) Log out"""


def ask_date(prompt):
    raw = input(prompt).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BankError("Dates must look like 2026-03-31.")


def show_statement(db, account):
    start = ask_date("From (YYYY-MM-DD, blank = 30 days ago): ")
    end = ask_date("To (YYYY-MM-DD, blank = today): ")
    st = statements.get_statement(db, account, start, end)
    print(f"\nStatement {st.start} to {st.end}")
    if not st.lines:
        print("No transactions in this period.")
    else:
        for l in st.lines[-10:]:
            print(f"{l.time:%Y-%m-%d %H:%M}  {l.type:<13} {l.other_account or '':<10} "
                  f"{l.amount:>12,.2f} {l.balance:>12,.2f}")
        if len(st.lines) > 10:
            print(f"(showing the last 10 of {len(st.lines)}; save as CSV to get them all)")
    path = input("Save everything in this period as a CSV file? "
                 "Enter a file name (blank to skip): ").strip()
    if path:
        try:
            with open(path, "x", newline="") as f:  # "x": never overwrite an existing file
                f.write(statements.to_csv(st))
        except OSError as e:
            raise BankError(f"Couldn't save the file: {e.strerror or e}")
        print(f"Saved {len(st.lines)} lines to {path}.")


def account_menu(db, account):
    while True:
        print(MENU)
        choice = input("> ").strip()
        try:
            if choice == "1":
                print(f"Balance: ${services.get_balance(db, account):,.2f}")
            elif choice == "2":
                txn = services.deposit(db, account, input("Amount: "))
                print(f"Deposited ${txn.amount:,.2f}. Balance: ${txn.balance_after:,.2f}")
            elif choice == "3":
                txn = services.withdraw(db, account, input("Amount: "))
                print(f"Withdrew ${txn.amount:,.2f}. Balance: ${txn.balance_after:,.2f}")
            elif choice == "4":
                to = input("Recipient account number: ")
                txn = services.transfer(db, account, to, input("Amount: "))
                print(f"Sent ${txn.amount:,.2f} to account {txn.counterparty}. "
                      f"Balance: ${txn.balance_after:,.2f}")
            elif choice == "5":
                show_statement(db, account)
            elif choice == "6":
                return
            else:
                print("Unknown option.")
        except BankError as e:
            print(f"Error: {e}")


def cmd_login(args):
    number = input("Account number: ").strip()
    pin = getpass("PIN: ")
    with SessionLocal() as db:
        token = services.login(db, number, pin)
        account = services.account_for_token(db, token)
        print(f"Welcome, {account.owner}.")
        account_menu(db, account)


def cmd_unlock(args):
    if len(args) != 1:
        raise BankError("Usage: python cli.py unlock <account number>")
    username = input("Admin username: ").strip()
    password = getpass("Admin password: ")
    with SessionLocal() as db:
        services.admin_login(db, username, password)  # raises if wrong
        services.unlock_account(db, args[0])
    print(f"Account {args[0]} unlocked.")


COMMANDS = {"open": cmd_open, "login": cmd_login, "unlock": cmd_unlock}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__)
        return 2
    init_db()
    try:
        with SessionLocal() as db:
            services.ensure_admin(db)
        COMMANDS[argv[1]](argv[2:])
    except BankError as e:
        print(f"Error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
