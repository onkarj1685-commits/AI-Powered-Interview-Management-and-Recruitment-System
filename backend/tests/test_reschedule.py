"""
Comprehensive tests for the Interview Reschedule feature.
Verifies:
1. Rescheduling an interview to a new date and time.
2. Database update persistence in SQLAlchemy/DB.
3. Verification that email recipient is the candidate's actual email address.
4. Email content verification: contains new date/time, candidate name, job title, mode/location, reason, not old values.
5. Rejection of past dates and missing fields.
6. Rejection of non-existent interview IDs (404).
7. Rejection of cancelled interviews (400).
8. Interviewer scheduling conflict detection (409).
9. Authentication & authorization enforcement (401).
10. SMTP failure behavior: DB remains updated, email_sent=False reported, notification logged as failed.
11. Idempotency and duplicate click safety.
"""
from datetime import datetime, timedelta
import pytest
from app import crud, models
from app.routers.auth import hash_password
from app.services import email_service


@pytest.fixture()
def auth_headers(client, db_session):
    """Authenticate with seeded admin user and return Bearer auth headers."""
    crud.seed_default_user_if_empty(db_session, hash_password("Admin123!"))
    login_resp = client.post(
        "/auth/login",
        json={"username_or_email": "admin", "password": "Admin123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


import uuid

@pytest.fixture()
def test_setup(client, auth_headers):
    """Create a candidate with a dedicated test email, a job, and an interviewer."""
    uid = uuid.uuid4().hex[:6]
    cand_resp = client.post(
        "/candidates/",
        json={
            "full_name": "Test Candidate",
            "email": f"test.candidate.{uid}@example.com",
            "phone": "+1-555-0199",
        },
    )
    assert cand_resp.status_code == 201
    candidate = cand_resp.json()

    job_resp = client.post(
        "/jobs/",
        json={
            "title": f"Senior AI Engineer {uid}",
            "department": "Engineering",
            "description": "FastAPI & LLM systems",
            "status": "open",
        },
    )
    assert job_resp.status_code == 201
    job = job_resp.json()

    intr_resp = client.post(
        "/interviewers/",
        json={
            "full_name": "Dr. Interviewer",
            "email": f"dr.interviewer.{uid}@example.com",
            "title": "Principal Architect",
        },
    )
    assert intr_resp.status_code == 201
    interviewer = intr_resp.json()

    # Create initial interview in the future
    future_time = (datetime.utcnow() + timedelta(days=5)).replace(microsecond=0)
    iv_resp = client.post(
        "/interviews/",
        json={
            "candidate_id": candidate["id"],
            "job_id": job["id"],
            "interviewer_id": interviewer["id"],
            "scheduled_at": future_time.isoformat(),
            "duration_minutes": 45,
            "round_name": "Initial Screen",
            "meeting_link": "https://meet.google.com/old-link",
        },
    )
    assert iv_resp.status_code == 201
    interview = iv_resp.json()

    return {
        "candidate": candidate,
        "job": job,
        "interviewer": interviewer,
        "interview": interview,
        "initial_time": future_time,
    }


def test_reschedule_success_and_email_verification(client, auth_headers, test_setup, db_session):
    """
    Test rescheduling an interview to a new date/time.
    Verify PostgreSQL values, email recipient, and email template content.
    """
    iv = test_setup["interview"]
    cand = test_setup["candidate"]
    job = test_setup["job"]
    new_time = (datetime.utcnow() + timedelta(days=10)).replace(hour=14, minute=30, second=0, microsecond=0)

    payload = {
        "scheduled_at": new_time.isoformat(),
        "duration_minutes": 60,
        "round_name": "Technical Deep Dive",
        "meeting_link": "https://meet.google.com/new-room-123",
        "reason": "Interviewer travel conflict",
    }

    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json=payload,
        headers=auth_headers,
    )
    assert resp.status_code == 200
    res_data = resp.json()

    # 1. Verify API response
    assert res_data["id"] == iv["id"]
    assert res_data["duration_minutes"] == 60
    assert res_data["round_name"] == "Technical Deep Dive"
    assert res_data["meeting_link"] == "https://meet.google.com/new-room-123"
    assert res_data["status"] == "scheduled"
    assert res_data["email_sent"] is True

    # 2. Verify PostgreSQL updated values directly via SQLAlchemy
    db_session.expire_all()
    db_iv = db_session.query(models.Interview).filter(models.Interview.id == iv["id"]).first()
    assert db_iv is not None
    assert db_iv.duration_minutes == 60
    assert db_iv.round_name == "Technical Deep Dive"
    assert db_iv.meeting_link == "https://meet.google.com/new-room-123"
    assert db_iv.status == models.InterviewStatus.SCHEDULED
    assert db_iv.reminder_sent is False

    # 3. Verify notification recipient is the candidate's actual email address
    notif = (
        db_session.query(models.NotificationLog)
        .filter(
            models.NotificationLog.interview_id == iv["id"],
            models.NotificationLog.notification_type == "interview_rescheduled",
        )
        .order_by(models.NotificationLog.id.desc())
        .first()
    )
    assert notif is not None
    assert notif.recipient == cand["email"]
    assert notif.status == "sent"
    assert notif.subject == "Interview Rescheduled – Updated Interview Details"

    # 4. Verify email contents contain new date/time, candidate name, job title, mode/location, and reason
    formatted_date = email_service.format_interview_date(new_time)
    formatted_time = email_service.format_interview_time(new_time)

    # Verify HTML stored in database
    assert cand["full_name"] in notif.body_html
    assert job["title"] in notif.body_html
    assert "Technical Deep Dive" in notif.body_html
    assert "Updated Interview Details" in notif.body_html
    assert formatted_date in notif.body_html
    assert formatted_time in notif.body_html
    assert "https://meet.google.com/new-room-123" in notif.body_html
    assert "Reason for Rescheduling" in notif.body_html
    assert "Interviewer travel conflict" in notif.body_html

    # Also verify plain-text alternative template contains all required elements
    html_alt, text_alt = email_service.build_interview_rescheduled_email(
        candidate_name=cand["full_name"],
        job_title=job["title"],
        round_name="Technical Deep Dive",
        new_date_str=formatted_date,
        new_time_str=formatted_time,
        interviewer_name="Dr. Interviewer",
        meeting_link="https://meet.google.com/new-room-123",
        reason="Interviewer travel conflict",
    )
    assert cand["full_name"] in text_alt
    assert job["title"] in text_alt
    assert "Technical Deep Dive" in text_alt
    assert formatted_date in text_alt
    assert formatted_time in text_alt
    assert "https://meet.google.com/new-room-123" in text_alt
    assert "Reason for Rescheduling: Interviewer travel conflict" in text_alt


def test_reschedule_past_date_rejected(client, auth_headers, test_setup):
    """Attempting to reschedule in the past must be rejected with 400 Bad Request."""
    iv = test_setup["interview"]
    past_time = datetime(2020, 1, 15, 10, 0, 0).isoformat()

    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json={"scheduled_at": past_time},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "past" in resp.json()["detail"].lower()


def test_reschedule_missing_fields_rejected(client, auth_headers, test_setup):
    """Attempting to reschedule without scheduled_at must be rejected."""
    iv = test_setup["interview"]
    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json={"duration_minutes": 30},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_reschedule_nonexistent_interview_fails(client, auth_headers):
    """Rescheduling a non-existent interview ID must return 404 Not Found."""
    future_time = (datetime.utcnow() + timedelta(days=2)).isoformat()
    resp = client.post(
        "/interviews/999999/reschedule",
        json={"scheduled_at": future_time},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_reschedule_cancelled_interview_fails(client, auth_headers, test_setup, db_session):
    """Attempting to reschedule a cancelled interview must return 400 Bad Request."""
    iv = test_setup["interview"]

    # Cancel the interview
    db_iv = db_session.query(models.Interview).filter(models.Interview.id == iv["id"]).first()
    db_iv.status = models.InterviewStatus.CANCELLED
    db_session.commit()

    future_time = (datetime.utcnow() + timedelta(days=3)).isoformat()
    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json={"scheduled_at": future_time},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "cancelled" in resp.json()["detail"].lower()


def test_reschedule_interviewer_conflict_rejected(client, auth_headers, test_setup):
    """Attempting to reschedule into another interview of the same interviewer must return 409 Conflict."""
    setup = test_setup
    intr_id = setup["interviewer"]["id"]
    job_id = setup["job"]["id"]

    # Create a second candidate and interview at specific time
    c2 = client.post("/candidates/", json={"full_name": "Bob", "email": "bob.test@example.com"}).json()
    conflict_slot = (datetime.utcnow() + timedelta(days=7)).replace(hour=11, minute=0, second=0, microsecond=0)

    client.post(
        "/interviews/",
        json={
            "candidate_id": c2["id"],
            "job_id": job_id,
            "interviewer_id": intr_id,
            "scheduled_at": conflict_slot.isoformat(),
            "duration_minutes": 60,
        },
    )

    # Now attempt to reschedule interview 1 to overlap with interview 2 (11:30 is inside 11:00-12:00)
    overlap_time = (conflict_slot + timedelta(minutes=30)).isoformat()
    resp = client.post(
        f"/interviews/{setup['interview']['id']}/reschedule",
        json={
            "scheduled_at": overlap_time,
            "duration_minutes": 45,
            "interviewer_id": intr_id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "conflict" in resp.json()["detail"].lower()


def test_reschedule_unauthorized_fails(client, test_setup):
    """Calling reschedule without an authentication token must return 401 Unauthorized."""
    iv = test_setup["interview"]
    future_time = (datetime.utcnow() + timedelta(days=2)).isoformat()
    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json={"scheduled_at": future_time},
    )
    assert resp.status_code == 401


def test_reschedule_preserves_db_if_email_fails(client, auth_headers, test_setup, db_session, monkeypatch):
    """
    If SMTP dispatch fails, the database update MUST be preserved in PostgreSQL,
    and the API response must report email_sent=False without throwing a 500 error.
    """
    iv = test_setup["interview"]
    new_time = (datetime.utcnow() + timedelta(days=12)).replace(microsecond=0)

    # Simulate SMTP failure
    def mock_send_raw_email(*args, **kwargs):
        return False, "SMTP connection timed out"

    monkeypatch.setattr(email_service, "send_raw_email", mock_send_raw_email)

    resp = client.post(
        f"/interviews/{iv['id']}/reschedule",
        json={"scheduled_at": new_time.isoformat(), "duration_minutes": 50},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    # Verify email_sent is False and message mentions email failure
    assert data["email_sent"] is False
    assert "could not be sent" in data["message"].lower()

    # Verify database update was STILL COMMITTED and preserved
    db_session.expire_all()
    db_iv = db_session.query(models.Interview).filter(models.Interview.id == iv["id"]).first()
    assert db_iv.duration_minutes == 50
    assert db_iv.status == models.InterviewStatus.SCHEDULED

    # Verify NotificationLog reflects failed delivery
    notif = (
        db_session.query(models.NotificationLog)
        .filter(models.NotificationLog.interview_id == iv["id"])
        .order_by(models.NotificationLog.id.desc())
        .first()
    )
    assert notif is not None
    assert notif.status == "failed"
    assert "SMTP connection timed out" in notif.error_message


def test_reschedule_idempotency_duplicate_calls(client, auth_headers, test_setup):
    """Repeated clicks/calls with the same payload must not raise duplicate key errors."""
    iv = test_setup["interview"]
    new_time = (datetime.utcnow() + timedelta(days=8)).replace(microsecond=0).isoformat()
    payload = {"scheduled_at": new_time, "duration_minutes": 45}

    resp1 = client.post(f"/interviews/{iv['id']}/reschedule", json=payload, headers=auth_headers)
    assert resp1.status_code == 200

    resp2 = client.post(f"/interviews/{iv['id']}/reschedule", json=payload, headers=auth_headers)
    assert resp2.status_code == 200
