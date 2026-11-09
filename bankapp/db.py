from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from bankapp import config


class Base(DeclarativeBase):
    pass


engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db(bind=None):
    """Create all tables (no migrations yet; fine for this project's size)."""
    from bankapp import models  # noqa: F401  (registers tables on Base)

    eng = bind or engine
    Base.metadata.create_all(eng)
    # create_all never alters existing tables. Databases made before step 5 lack this column.
    with eng.begin() as conn:
        conn.execute(text(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS counterparty VARCHAR(10)"))
