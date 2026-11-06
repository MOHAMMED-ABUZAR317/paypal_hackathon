"""Test configuration.

Environment is set *before* any app module import, so the cached Settings object
is already pointed at an isolated test database and mock PayPal.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ["ENV"] = "test"
os.environ["AUTO_SEED"] = "false"
os.environ["POLL_INTERVAL_MINUTES"] = "0"
os.environ["PAYPAL_MODE"] = "mock"
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""
os.environ["OPERATOR_API_KEY"] = "test-operator-key"
os.environ["SEED_MEMBERS"] = "80"
os.environ["AI_API_KEY"] = ""

TEST_DB = Path(__file__).resolve().parent.parent / "data" / "test_raincheck.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

OPERATOR_HEADERS = {"X-Operator-Key": "test-operator-key"}


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded_client(client):
    db = SessionLocal()
    try:
        seed(db, member_count=80)
    finally:
        db.close()
    return client


@pytest.fixture()
def db_session():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
