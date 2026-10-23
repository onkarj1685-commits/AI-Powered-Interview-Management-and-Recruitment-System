"""
Tests for Email Notification Integration:
- SMTP configuration & status checks
- Interview scheduling email dispatch
- 24-hour interview reminder background checks & duplicate prevention
- Application status notifications (Shortlisted, Selected, Rejected)
- Rescheduling & Cancellation notification triggers
- HR notifications on new candidates
- Delivery logs, audit history, and retry mechanics
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from app import crud, models
from app.services import email_service


def test_smtp_status_endpoint(client):
    """Verify SMTP status endpoint returns diagnostic summary without passwords."""
    resp = client.get("/notifications/smtp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert "smtp_host" in data
    assert "smtp_port" in data
    assert "email_from" in data
    assert "password" not in data  # Never expose passwords


def test_send_test_email(client):
    """Test HR/Admin can trigger a test email."""
    resp = client.post(
        "/notifications/test",
        json={"to_email": "candidate@example.com", "notes": "Verifying test setup"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recipient"] == "candidate@example.com"
    assert data["notification_type"] == "test_email"
    assert data["status"] in ["sent", "pending"]


def test_interview_scheduling_triggers_email(client, sample_candidate, sample_job, sample_interviewer, db_session):
    """
    Requirement 2.A: When HR schedules an interview, automatically send an email to the candidate.
    """
    scheduled_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    resp = client.post(
        "/interviews/",
        json={
            "candidate_id": sample_candidate["id"],
            "job_id": sample_job["id"],
            "interviewer_id": sample_interviewer["id"],
            "scheduled_at": scheduled_time,
            "duration_minutes": 45,
            "round_name": "Technical Deep Dive",
            "meeting_link": "https://meet.google.com/abc-defg-hij",
            "instructions": "Please join with webcam on and laptop ready for code sharing.",
        },
    )
    assert resp.status_code == 201
    iv_data = resp.json()
    assert iv_data["meeting_link"] == "https://meet.google.com/abc-defg-hij"

    # Verify notification log was created for the candidate
    logs = crud.list_notification_logs(db_session, recipient=sample_candidate["email"])
    assert len(logs) >= 1
    sched_log = next((l for l in logs if l.notification_type == "interview_scheduled"), None)
    assert sched_log is not None
    assert sched_log.recipient == sample_candidate["email"]
    assert "Interview Scheduled" in sched_log.subject
    assert "Backend Engineer" in sched_log.subject
    assert "meet.google.com" in sched_log.body_html
    assert sched_log.status in ["sent", "pending"]


def test_candidate_status_update_notifications(client, sample_candidate, db_session):
    """
    Requirement 2.C: Send email notifications when HR changes candidate's status to
    Shortlisted, Selected, Rejected.
    """
    cid = sample_candidate["id"]

    # 1. Update to Shortlisted
    resp1 = client.patch(f"/candidates/{cid}/status", json={"status": "shortlisted", "notes": "Great resume fit"})
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "shortlisted"

    # Verify notification log
    logs1 = crud.list_notification_logs(db_session, recipient=sample_candidate["email"], notification_type="status_update")
    shortlisted_log = next((l for l in logs1 if "Shortlisted" in l.subject), None)
    assert shortlisted_log is not None
    assert "Shortlisted" in shortlisted_log.body_html

    # 2. Update to Selected
    resp2 = client.patch(f"/candidates/{cid}/status", json={"status": "selected"})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "selected"

    logs2 = crud.list_notification_logs(db_session, recipient=sample_candidate["email"], notification_type="status_update")
    selected_log = next((l for l in logs2 if "Selection" in l.subject or "Selected" in l.subject), None)
    assert selected_log is not None

    # 3. Update to Rejected
    resp3 = client.patch(f"/candidates/{cid}/status", json={"status": "rejected"})
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "rejected"

    logs3 = crud.list_notification_logs(db_session, recipient=sample_candidate["email"], notification_type="status_update")
    rejected_log = next((l for l in logs3 if "Update regarding" in l.subject), None)
    assert rejected_log is not None


def test_interview_rescheduling_and_cancellation(client, sample_interview, db_session):
    """
    Requirement 2.D: Rescheduling and Cancellation email notifications.
    """
    from app.routers.auth import hash_password
    crud.seed_default_user_if_empty(db_session, hash_password("Admin123!"))
    login_resp = client.post("/auth/login", json={"username_or_email": "admin", "password": "Admin123!"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    iv_id = sample_interview["id"]
    new_time = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()

    # 1. Reschedule
    resched_resp = client.post(
        f"/interviews/{iv_id}/reschedule",
        json={
            "scheduled_at": new_time,
            "meeting_link": "https://meet.google.com/new-link",
            "reason": "Interviewer calendar conflict",
        },
        headers=headers,
    )
    assert resched_resp.status_code == 200
    assert resched_resp.json()["meeting_link"] == "https://meet.google.com/new-link"

    resched_logs = crud.list_notification_logs(db_session, notification_type="interview_rescheduled")
    assert len(resched_logs) >= 1
    assert "Rescheduled" in resched_logs[0].subject

    # 2. Cancel
    cancel_resp = client.post(
        f"/interviews/{iv_id}/cancel",
        json={"reason": "Position filled internally"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    cancel_logs = crud.list_notification_logs(db_session, notification_type="interview_cancelled")
    assert len(cancel_logs) >= 1
    assert "Cancellation" in cancel_logs[0].subject or "Cancelled" in cancel_logs[0].subject


def test_24_hour_reminder_background_check(client, sample_candidate, sample_job, sample_interviewer, db_session):
    """
    Requirement 2.B: Automatically send reminder 24 hours before interview,
    track reminder status in PostgreSQL, and prevent duplicate reminders.
    """
    # Create interview scheduled 18 hours from now (within the 24h window)
    upcoming_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=18)
    iv = models.Interview(
        candidate_id=sample_candidate["id"],
        job_id=sample_job["id"],
        interviewer_id=sample_interviewer["id"],
        scheduled_at=upcoming_time,
        duration_minutes=45,
        round_name="Final Round",
        meeting_link="https://meet.google.com/reminder-test",
        status=models.InterviewStatus.SCHEDULED,
        reminder_sent=False,
    )
    db_session.add(iv)
    db_session.commit()
    db_session.refresh(iv)

    assert iv.reminder_sent is False

    # Execute reminder check using session
    processed = email_service.check_and_send_interview_reminders()
    assert processed >= 1

    # Verify iv.reminder_sent is now True in DB
    db_session.refresh(iv)
    assert iv.reminder_sent is True
    assert iv.reminder_sent_at is not None

    # Running check again immediately must NOT send duplicate reminder
    processed_again = email_service.check_and_send_interview_reminders()
    assert processed_again == 0


def test_notification_stats_and_retry(client, db_session):
    """Test notification stats and retry endpoints."""
    # Create a simulated failed log
    log = models.NotificationLog(
        recipient="fail@example.com",
        notification_type="interview_scheduled",
        subject="Failed Test",
        body_html="<p>Test</p>",
        status="failed",
        error_message="Simulated connection error",
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    # Check stats endpoint
    stats_resp = client.get("/notifications/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total"] >= 1
    assert stats["failed"] >= 1

    # Retry the notification
    retry_resp = client.post(f"/notifications/{log.id}/retry")
    assert retry_resp.status_code == 200
    retried_data = retry_resp.json()
    assert retried_data["retry_count"] == 1


def test_manual_interview_reminder_endpoint(client, sample_interview, db_session):
    """Test manual reminder button endpoint dispatches reminder."""
    iv_id = sample_interview["id"]
    resp = client.post(f"/interviews/{iv_id}/send-reminder")
    assert resp.status_code == 200
    data = resp.json()
    assert data["notification_type"] == "interview_reminder"
    assert data["status"] in ["sent", "pending"]
    assert "Reminder: Your Interview is Coming Up" in data["subject"] or "Reminder" in data["subject"]


def test_manual_reminder_returns_502_when_smtp_unconfigured(client, sample_interview, monkeypatch):
    """When in production mode without SMTP credentials, endpoint returns 502."""
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("SMTP_USERNAME", "your_sender_email@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "your_google_app_password")

    iv_id = sample_interview["id"]
    resp = client.post(f"/interviews/{iv_id}/send-reminder")
    assert resp.status_code == 502
    assert "not configured" in resp.json()["detail"].lower()


def test_email_template_exact_format():
    """Verify that the template produces the exact Section 8 structure."""
    scheduled_dt = datetime(2026, 10, 15, 10, 0)
    html, text = email_service.build_interview_scheduled_email(
        candidate_name="Candidate",
        job_title="Software Developer",
        round_name="Technical",
        scheduled_at=scheduled_dt,
        duration_minutes=60,
        interviewer_name="HR Lead",
        meeting_link="https://meet.google.com/xyz",
    )

    assert "Dear Candidate," in text
    assert "Congratulations! Your interview has been scheduled." in text
    assert "Interview Details" in text
    assert "- Candidate Name: Candidate" in text
    assert "- Job Position: Software Developer" in text
    assert "- Interview Round: Technical" in text
    assert "- Interview Date: 15 October 2026" in text
    assert "- Interview Time: 10:00 AM" in text
    assert "- Interviewer: HR Lead" in text
    assert "Please be available at the scheduled time." in text
    assert "AI-Powered Interview Management and Recruitment System" in text
    assert "Software Developer" in html
    assert "15 October 2026" in html
    assert "10:00 AM" in html

    # Test Reminder template
    rem_html, rem_text = email_service.build_interview_reminder_email(
        candidate_name="Candidate",
        job_title="Software Developer",
        round_name="Technical",
        scheduled_at=scheduled_dt,
        duration_minutes=60,
        interviewer_name="HR Lead",
        meeting_link="https://meet.google.com/xyz",
    )
    assert "This is a friendly reminder about your upcoming interview." in rem_text
    assert "Please be ready at the scheduled time." in rem_text
    assert "Best of luck!" in rem_text

    # Test Rescheduled template
    resched_html, resched_text = email_service.build_interview_rescheduled_email(
        candidate_name="Candidate",
        job_title="Software Developer",
        round_name="Technical",
        new_date_str="20 October 2026",
        new_time_str="11:00 AM",
        interviewer_name="HR Lead",
    )
    assert "Your interview schedule has been updated." in resched_text
    assert "- New Date: 20 October 2026" in resched_text
    assert "- New Time: 11:00 AM" in resched_text

    # Test Cancellation template
    canc_html, canc_text = email_service.build_interview_cancelled_email(
        candidate_name="Candidate",
        job_title="Software Developer",
        round_name="Technical",
        previous_date_str="15 October 2026",
        previous_time_str="10:00 AM",
    )
    assert "We would like to inform you that your scheduled interview has been cancelled." in canc_text
    assert "- Previous Date: 15 October 2026" in canc_text
    assert "- Previous Time: 10:00 AM" in canc_text
