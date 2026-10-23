"""
Shared pytest fixtures.

Tests run against an in-memory SQLite database instead of PostgreSQL so
they're fast and require no external services. DATABASE_URL is overridden
*before* the app is imported, since app.main creates tables at import time.
Each test gets a fresh database via the `client` fixture.
"""
import os
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal, get_db


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------- Convenience factory fixtures ----------

@pytest.fixture()
def sample_candidate(client):
    resp = client.post(
        "/candidates/",
        json={"full_name": "Ada Lovelace", "email": "ada@example.com", "phone": "555-0100"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def sample_job(client):
    resp = client.post(
        "/jobs/",
        json={"title": "Backend Engineer", "department": "Engineering",
              "description": "Build APIs", "status": "open"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def sample_interviewer(client):
    resp = client.post(
        "/interviewers/",
        json={"full_name": "Grace Hopper", "email": "grace@example.com", "title": "Staff Engineer"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def sample_interview(client, sample_candidate, sample_job, sample_interviewer):
    resp = client.post(
        "/interviews/",
        json={
            "candidate_id": sample_candidate["id"],
            "job_id": sample_job["id"],
            "interviewer_id": sample_interviewer["id"],
            "scheduled_at": "2026-10-01T15:00:00",
            "duration_minutes": 60,
            "round_name": "Phone Screen",
        },
    )
    assert resp.status_code == 201
    return resp.json()
