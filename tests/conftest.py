"""Tests run against a separate test database in the Docker Postgres.

Every test drops and recreates the tables, so two test runs must never share a database.
The main checkout uses `bank_test`. A linked git worktree (where `.git` is a file) gets its
own `bank_test_<hash of its path>`, so agents working in parallel can't wipe each other's data.
Set BANK_TEST_DB to choose a name yourself.
"""
import hashlib
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from datetime import datetime
from zoneinfo import ZoneInfo

from bankapp import api, services
from bankapp.db import Base, init_db

def _test_db_name() -> str:
    name = os.environ.get("BANK_TEST_DB")
    if not name:
        root = Path(__file__).resolve().parent.parent
        if (root / ".git").is_file():  # a linked worktree
            name = "bank_test_" + hashlib.md5(str(root).encode()).hexdigest()[:8]
        else:
            name = "bank_test"
    # The name goes into CREATE DATABASE, which can't take a bind parameter: whitelist it.
    if not re.fullmatch(r"bank_test[a-z0-9_]*", name):
        raise RuntimeError(f"Unsafe test database name {name!r}: must match bank_test[a-z0-9_]*")
    return name


TEST_DB = _test_db_name()
ADMIN_URL = "postgresql+psycopg://bank:bank@localhost:5434/bank"
TEST_URL = f"postgresql+psycopg://bank:bank@localhost:5434/{TEST_DB}"


@pytest.fixture(scope="session")
def engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": TEST_DB})
        if not exists:
            conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()
    eng = create_engine(TEST_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """A session factory on a freshly emptied schema for every test."""
    Base.metadata.drop_all(engine)
    init_db(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def client(db):
    api.app.dependency_overrides[api.get_db] = lambda: db
    # No `with` block: skip the lifespan hook, which would touch the real database.
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


@pytest.fixture
def admin(db):
    return services.ensure_admin(db, "admin", "admin123")


# Tuesday 10 March 2026, 12:00 in Sydney: inside office hours.
FIXED_NOW = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("Australia/Sydney"))


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Every test runs at the same moment, so results don't depend on when you run them."""
    monkeypatch.setattr(services, "utcnow", lambda: FIXED_NOW)


@pytest.fixture
def set_clock(monkeypatch):
    """Move the banking clock for one test: set_clock(some_datetime)."""
    return lambda when: monkeypatch.setattr(services, "utcnow", lambda: when)
