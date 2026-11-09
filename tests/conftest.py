"""Tests run against a separate `bank_test` database in the Docker Postgres."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from datetime import datetime
from zoneinfo import ZoneInfo

from bankapp import api, services
from bankapp.db import Base, init_db

ADMIN_URL = "postgresql+psycopg://bank:bank@localhost:5434/bank"
TEST_URL = "postgresql+psycopg://bank:bank@localhost:5434/bank_test"


@pytest.fixture(scope="session")
def engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname='bank_test'"))
        if not exists:
            conn.execute(text("CREATE DATABASE bank_test"))
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
