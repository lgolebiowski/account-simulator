import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from bankapp import config, services
from bankapp.errors import AuthError, NotFoundError
from bankapp.models import Admin, AuthSession
from bankapp.security import verify_pin

ROOT = Path(__file__).resolve().parent.parent


def test_ensure_admin_creates_hashed_admin(db):
    services.ensure_admin(db, "root", "s3cret")
    stored = db.scalar(select(Admin).where(Admin.username == "root"))
    assert "s3cret" not in stored.password_hash
    assert verify_pin("s3cret", stored.password_hash)


def test_ensure_admin_is_idempotent_and_keeps_existing_password(db):
    services.ensure_admin(db, "root", "first")
    services.ensure_admin(db, "root", "second")
    assert len(db.scalars(select(Admin)).all()) == 1
    services.admin_login(db, "root", "first")  # original password still works


def test_ensure_admin_uses_config_when_args_omitted(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_USER", "boss")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "pw")
    services.ensure_admin(db)
    services.admin_login(db, "boss", "pw")


def test_config_defaults_to_admin_admin123_without_env():
    out = subprocess.run(
        [sys.executable, "-c",
         "from bankapp import config; print(config.ADMIN_USER, config.ADMIN_PASSWORD)"],
        env={"PATH": "/usr/bin"}, cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["admin", "admin123"]


def test_config_reads_admin_from_env():
    out = subprocess.run(
        [sys.executable, "-c",
         "from bankapp import config; print(config.ADMIN_USER, config.ADMIN_PASSWORD)"],
        env={"PATH": "/usr/bin", "BANK_ADMIN_USER": "u", "BANK_ADMIN_PASSWORD": "p"},
        cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["u", "p"]


def test_admin_login_wrong_password(db, admin):
    with pytest.raises(AuthError):
        services.admin_login(db, "admin", "nope")
    with pytest.raises(AuthError):
        services.admin_login(db, "ghost", "admin123")


def test_unlock_unknown_account(db, admin):
    with pytest.raises(NotFoundError):
        services.unlock_account(db, "0000000000")


def test_account_token_is_not_an_admin_token(db, admin):
    ann = services.open_account(db, "Ann", "1234")
    with pytest.raises(AuthError):
        services.admin_for_token(db, services.login(db, ann.number, "1234"))


def test_admin_token_is_not_an_account_token(db, admin):
    with pytest.raises(AuthError):
        services.account_for_token(db, services.admin_login(db, "admin", "admin123"))


def test_expired_token_rejected(db):
    ann = services.open_account(db, "Ann", "1234")
    token = services.login(db, ann.number, "1234")
    session = db.scalar(select(AuthSession))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(AuthError):
        services.account_for_token(db, token)


def test_token_is_not_stored_in_plain_text(db):
    ann = services.open_account(db, "Ann", "1234")
    token = services.login(db, ann.number, "1234")
    assert db.scalar(select(AuthSession)).token_hash != token
