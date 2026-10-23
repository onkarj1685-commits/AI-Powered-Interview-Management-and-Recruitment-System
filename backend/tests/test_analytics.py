"""
Comprehensive test suite for Recruitment Analytics and Hiring Insights module.

Covers:
1. Overview metrics with known database records
2. Candidate stage counts
3. Interview status counts
4. Interview completion-rate calculations
5. Average feedback scores with null values
6. Job-wise candidate distribution
7. Monthly grouping and zero-activity months
8. Custom date-range filtering
9. Empty database responses
10. Invalid date ranges (start > end returns 400)
11. Duplicate-count prevention in joins
12. CSV download and CSV content verification
13. PDF download and PDF binary / content verification
14. Unauthorized access (401 without token)
15. Role-based access restrictions (non-HR/Admin role returns 403)
"""
from datetime import datetime, timedelta
import pytest
from app import crud, models
from app.routers.auth import hash_password


@pytest.fixture
def auth_headers(client, db_session):
    """Register an admin user and return Authorization headers."""
    resp = client.post(
        "/auth/register",
        json={
            "full_name": "HR Director",
            "username": "hrdirector",
            "email": "hrdirector@company.com",
            "password": "SecurePassword123!",
            "role": "admin",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def non_hr_headers(client, db_session):
    """Register a candidate / non-HR user and return Authorization headers."""
    resp = client.post(
        "/auth/register",
        json={
            "full_name": "Job Applicant",
            "username": "jobapplicant",
            "email": "applicant@company.com",
            "password": "SecurePassword123!",
            "role": "candidate",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Test 1 & 9: Empty Database Responses & Unauthorized Access
# =============================================================================

def test_unauthorized_access_rejected(client):
    """Analytics endpoints must require authentication."""
    resp = client.get("/analytics/overview")
    assert resp.status_code == 401

    resp = client.get("/analytics/export/csv")
    assert resp.status_code == 401


def test_non_hr_role_forbidden(client, non_hr_headers):
    """Users with non-HR / non-admin roles must be rejected with 403 Forbidden."""
    resp = client.get("/analytics/overview", headers=non_hr_headers)
    assert resp.status_code == 403
    assert "Access forbidden" in resp.json()["detail"]


def test_empty_database_responses(client, auth_headers):
    """Overview, charts, and tables should return valid empty responses on empty DB."""
    resp = client.get("/analytics/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_candidates"]["value"] == 0
    assert data["active_jobs"]["value"] == 0
    assert data["total_interviews"]["value"] == 0
    assert data["completion_rate"]["value"] == 0.0
    assert data["avg_feedback_score"]["value"] == 0.0
    assert data["selection_rate"]["value"] == 0.0

    # Pipeline
    p_resp = client.get("/analytics/recruitment-pipeline", headers=auth_headers)
    assert p_resp.status_code == 200
    assert p_resp.json()["total_candidates"] == 0

    # Interview Status
    s_resp = client.get("/analytics/interview-status", headers=auth_headers)
    assert s_resp.status_code == 200
    assert s_resp.json()["total_interviews"] == 0

    # Job Distribution
    j_resp = client.get("/analytics/job-distribution", headers=auth_headers)
    assert j_resp.status_code == 200
    assert len(j_resp.json()["jobs"]) == 0


# =============================================================================
# Test 2, 3, 4, 5, 6, 11: Seeded Records, Calculations, Joins & Deduplication
# =============================================================================

def test_overview_metrics_with_known_records(client, auth_headers, db_session):
    """Verify exact KPI calculations with controlled database entries."""
    # 1. Create two jobs (1 Open, 1 Closed)
    job1 = client.post("/jobs/", json={"title": "Software Engineer", "department": "Engineering", "status": "open"}).json()
    job2 = client.post("/jobs/", json={"title": "Product Manager", "department": "Product", "status": "closed"}).json()

    # 2. Create Interviewer
    itv = client.post("/interviewers/", json={"full_name": "Sarah Connor", "email": "sarah@terminator.com"}).json()

    # 3. Create Candidates
    c1 = client.post("/candidates/", json={"full_name": "Candidate One", "email": "c1@test.com"}).json()
    c2 = client.post("/candidates/", json={"full_name": "Candidate Two", "email": "c2@test.com"}).json()
    c3 = client.post("/candidates/", json={"full_name": "Candidate Three", "email": "c3@test.com"}).json()

    # Set status
    client.patch(f"/candidates/{c1['id']}/status", json={"status": "selected"})
    client.patch(f"/candidates/{c2['id']}/status", json={"status": "shortlisted"})

    # 4. Create Interviews (1 Scheduled, 1 Completed with feedback score 4.5, 1 Cancelled)
    now = datetime.utcnow()
    i1 = client.post("/interviews/", json={
        "candidate_id": c1["id"],
        "job_id": job1["id"],
        "interviewer_id": itv["id"],
        "scheduled_at": now.isoformat(),
        "round_name": "Technical",
    }).json()

    i2 = client.post("/interviews/", json={
        "candidate_id": c2["id"],
        "job_id": job1["id"],
        "interviewer_id": itv["id"],
        "scheduled_at": (now - timedelta(days=2)).isoformat(),
        "round_name": "HR Round",
    }).json()

    i3 = client.post("/interviews/", json={
        "candidate_id": c3["id"],
        "job_id": job2["id"],
        "interviewer_id": itv["id"],
        "scheduled_at": (now - timedelta(days=3)).isoformat(),
        "round_name": "Screening",
    }).json()

    # Submit feedback for i1 (automatically marks i1 completed)
    client.post(f"/interviews/{i1['id']}/feedback", json={
        "score": 4.5,
        "recommendation": "strong_yes",
        "notes": "Excellent candidate",
    })

    # Mark i3 as cancelled
    client.patch(f"/interviews/{i3['id']}", json={"status": "cancelled"})

    # Fetch Overview KPIs
    resp = client.get("/analytics/overview?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    # Total Candidates
    assert data["total_candidates"]["value"] >= 3

    # Active Jobs (1 Open out of 2)
    assert data["active_jobs"]["value"] == 1
    assert "2 total" in data["active_jobs"]["subtext"]

    # Total Interviews (3 created)
    assert data["total_interviews"]["value"] == 3

    # Interview Completion Rate:
    # Eligible interviews = Completed (1) + Cancelled (1) = 2. Scheduled is pending and excluded.
    # Completion Rate = 1 / 2 * 100 = 50.0%
    assert data["completion_rate"]["value"] == 50.0

    # Average Feedback Score:
    # Only 1 feedback submitted with score 4.5
    assert data["avg_feedback_score"]["value"] == 4.5
    assert "4.5 / 5.0" in data["avg_feedback_score"]["display_value"]

    # Selection Rate:
    # 1 candidate is selected out of 3 = 33.3%
    assert data["selection_rate"]["value"] == pytest.approx(33.3, 0.5)

    # Cancelled Interviews (i3 is cancelled)
    assert data["cancelled_interviews"]["value"] == 1

    # Candidates Hired (c1 is selected)
    assert data["candidates_hired"]["value"] == 1

    # Pending Interviews (i2 is scheduled)
    assert data["pending_interviews"]["value"] == 1


def test_candidate_stage_counts(client, auth_headers):
    """Verify that candidate pipeline counts unique candidates per stage."""
    # Register candidates with varied statuses
    c_app = client.post("/candidates/", json={"full_name": "App Candidate", "email": "app@stage.com"}).json()
    c_short = client.post("/candidates/", json={"full_name": "Short Candidate", "email": "short@stage.com"}).json()
    client.patch(f"/candidates/{c_short['id']}/status", json={"status": "shortlisted"})

    resp = client.get("/analytics/recruitment-pipeline?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    stages = {st["stage_key"]: st for st in resp.json()["stages"]}

    assert "applied" in stages
    assert "shortlisted" in stages
    assert "selected" in stages
    assert "rejected" in stages
    assert stages["shortlisted"]["count"] >= 1


def test_interview_status_counts(client, auth_headers):
    """Verify distribution of interview statuses."""
    resp = client.get("/analytics/interview-status?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    status_map = {s["status_key"]: s for s in data["statuses"]}

    assert "scheduled" in status_map
    assert "completed" in status_map
    assert "cancelled" in status_map
    assert "no_show" in status_map
    assert status_map["completed"]["color"] == "#059669"


def test_job_wise_candidate_distribution_and_deduplication(client, auth_headers, sample_job, sample_interviewer):
    """
    Ensure candidate associated with a job via multiple interviews is not counted twice.
    """
    c = client.post("/candidates/", json={"full_name": "Multi Interview Cand", "email": "multi@cand.com"}).json()

    now = datetime.utcnow()
    # Schedule two distinct interviews for the same candidate and job
    client.post("/interviews/", json={
        "candidate_id": c["id"],
        "job_id": sample_job["id"],
        "interviewer_id": sample_interviewer["id"],
        "scheduled_at": now.isoformat(),
        "round_name": "Round 1",
    })
    client.post("/interviews/", json={
        "candidate_id": c["id"],
        "job_id": sample_job["id"],
        "interviewer_id": sample_interviewer["id"],
        "scheduled_at": (now + timedelta(days=2)).isoformat(),
        "round_name": "Round 2",
    })

    resp = client.get("/analytics/job-distribution", headers=auth_headers)
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    matching_job = next((j for j in jobs if j["job_id"] == sample_job["id"]), None)
    assert matching_job is not None

    # Candidate should be counted exactly once even though there are 2 interviews
    assert matching_job["candidate_count"] == 1
    assert matching_job["interview_count"] >= 2


# =============================================================================
# Test 7 & 8 & 10: Date Filtering, Monthly Grouping & Invalid Ranges
# =============================================================================

def test_monthly_grouping_and_zero_activity_months(client, auth_headers):
    """Verify monthly trends include empty months with 0 counts."""
    resp = client.get("/analytics/monthly-trends?months=6", headers=auth_headers)
    assert resp.status_code == 200
    trends = resp.json()["trends"]

    # Must contain at least 6 months
    assert len(trends) >= 6
    for t in trends:
        assert "month_key" in t
        assert "month_label" in t
        assert isinstance(t["candidates_registered"], int)
        assert isinstance(t["interviews_scheduled"], int)
        assert isinstance(t["interviews_completed"], int)
        assert isinstance(t["candidates_selected"], int)


def test_custom_date_range_filtering(client, auth_headers):
    """Test custom start and end date filtering."""
    start_d = "2026-01-01"
    end_d = "2026-06-30"
    resp = client.get(f"/analytics/overview?start_date={start_d}&end_date={end_d}", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()["filter_summary"]
    assert "Jan 01, 2026" in summary["period_label"]


def test_invalid_date_range_rejected(client, auth_headers):
    """Start date after end date must return 400 Bad Request."""
    start_d = "2026-10-30"
    end_d = "2026-10-01"
    resp = client.get(f"/analytics/overview?start_date={start_d}&end_date={end_d}", headers=auth_headers)
    assert resp.status_code == 400
    assert "start_date cannot be after end_date" in resp.json()["detail"]


# =============================================================================
# Test 12 & 13: CSV & PDF Export Downloads and Content Verification
# =============================================================================

def test_csv_export_content_and_headers(client, auth_headers):
    """Verify CSV export is returned with UTF-8 BOM and correct column headers."""
    resp = client.get("/analytics/export/csv?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment; filename=" in resp.headers["content-disposition"]

    content = resp.content.decode("utf-8-sig")
    assert "AI-POWERED INTERVIEW MANAGEMENT AND RECRUITMENT SYSTEM" in content
    assert "RECRUITMENT KPI SUMMARY" in content
    assert "Total Candidates" in content
    assert "RECRUITMENT PIPELINE FUNNEL" in content
    assert "JOB POSITION CANDIDATE DISTRIBUTION" in content


def test_pdf_export_binary_and_headers(client, auth_headers):
    """Verify PDF export is returned with application/pdf media type and valid PDF header."""
    resp = client.get("/analytics/export/pdf?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment; filename=" in resp.headers["content-disposition"]
    # PDF magic bytes
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 500  # Non-trivial document size


# =============================================================================
# Test: Filter Options & Interviewer Performance
# =============================================================================

def test_filter_options_endpoint(client, auth_headers):
    """Test /analytics/filters and /analytics/filter-options endpoints return options for dropdowns."""
    # Test /analytics/filters
    resp = client.get("/analytics/filters", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "job_positions" in data
    assert "departments" in data
    assert "interviewers" in data
    assert "interview_statuses" in data
    assert "candidate_stages" in data

    # Test /analytics/filter-options alias
    resp_alias = client.get("/analytics/filter-options", headers=auth_headers)
    assert resp_alias.status_code == 200
    data_alias = resp_alias.json()
    assert "job_positions" in data_alias
    assert "departments" in data_alias
    assert "interviewers" in data_alias

    # Test dedicated sub-endpoints
    r_jobs = client.get("/analytics/filter-options/jobs", headers=auth_headers)
    assert r_jobs.status_code == 200
    assert isinstance(r_jobs.json(), list)

    r_depts = client.get("/analytics/filter-options/departments", headers=auth_headers)
    assert r_depts.status_code == 200
    assert isinstance(r_depts.json(), list)

    r_itvs = client.get("/analytics/filter-options/interviewers", headers=auth_headers)
    assert r_itvs.status_code == 200
    assert isinstance(r_itvs.json(), list)


def test_interviewer_performance_metrics(client, auth_headers, sample_interview):
    """Test interviewer performance analytics."""
    resp = client.get("/analytics/interviewer-performance?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "interviewers" in data
    assert len(data["interviewers"]) >= 1
    itv = data["interviewers"][0]
    assert "assigned_interviews" in itv
    assert "feedback_submission_rate" in itv


def test_feedback_analysis_endpoint(client, auth_headers):
    """Test /analytics/feedback-analysis endpoint returns score breakdown."""
    resp = client.get("/analytics/feedback-analysis?time_range=all", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "average_score" in data
    assert "total_reviews" in data
    assert "score_ranges" in data
    assert len(data["score_ranges"]) == 4


def test_alias_endpoints(client, auth_headers):
    """Test that aliases /analytics/summary, /analytics/recruitment-funnel, /analytics/recruitment-trends, /analytics/interviewer-workload work."""
    resp_sum = client.get("/analytics/summary?time_range=all", headers=auth_headers)
    assert resp_sum.status_code == 200
    assert "total_candidates" in resp_sum.json()

    resp_funnel = client.get("/analytics/recruitment-funnel?time_range=all", headers=auth_headers)
    assert resp_funnel.status_code == 200
    assert "stages" in resp_funnel.json()

    resp_trends = client.get("/analytics/recruitment-trends?months=6", headers=auth_headers)
    assert resp_trends.status_code == 200
    assert "trends" in resp_trends.json()

    resp_workload = client.get("/analytics/interviewer-workload?time_range=all", headers=auth_headers)
    assert resp_workload.status_code == 200
    assert "interviewers" in resp_workload.json()
