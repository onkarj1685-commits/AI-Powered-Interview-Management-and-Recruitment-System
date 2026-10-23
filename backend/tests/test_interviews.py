def test_create_interview(client, sample_candidate, sample_job, sample_interviewer):
    resp = client.post(
        "/interviews/",
        json={
            "candidate_id": sample_candidate["id"],
            "job_id": sample_job["id"],
            "interviewer_id": sample_interviewer["id"],
            "scheduled_at": "2026-11-05T10:00:00",
            "duration_minutes": 30,
            "round_name": "Recruiter Screen",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "scheduled"
    assert data["round_name"] == "Recruiter Screen"


def test_create_interview_unknown_candidate_fails(client, sample_job, sample_interviewer):
    resp = client.post(
        "/interviews/",
        json={
            "candidate_id": 99999,
            "job_id": sample_job["id"],
            "interviewer_id": sample_interviewer["id"],
            "scheduled_at": "2026-11-05T10:00:00",
        },
    )
    assert resp.status_code == 404


def test_get_interview_detail_includes_nested_objects(client, sample_interview):
    resp = client.get(f"/interviews/{sample_interview['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate"]["id"] == sample_interview["candidate_id"]
    assert data["job"]["id"] == sample_interview["job_id"]
    assert data["interviewer"]["id"] == sample_interview["interviewer_id"]


def test_filter_interviews_by_candidate(client, sample_interview, sample_candidate):
    resp = client.get("/interviews/", params={"candidate_id": sample_candidate["id"]})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["id"] == sample_interview["id"]


def test_update_interview_status(client, sample_interview):
    resp = client.patch(
        f"/interviews/{sample_interview['id']}", json={"status": "cancelled"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_delete_interview(client, sample_interview):
    resp = client.delete(f"/interviews/{sample_interview['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/interviews/{sample_interview['id']}")
    assert resp.status_code == 404


# ---------- Feedback ----------

def test_submit_feedback_marks_interview_completed(client, sample_interview):
    resp = client.post(
        f"/interviews/{sample_interview['id']}/feedback",
        json={
            "score": 4.5,
            "recommendation": "strong_yes",
            "strengths": "Excellent problem solving",
            "concerns": "None",
            "notes": "Would be a great addition to the team.",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["recommendation"] == "strong_yes"

    interview_resp = client.get(f"/interviews/{sample_interview['id']}")
    assert interview_resp.json()["status"] == "completed"


def test_submit_duplicate_feedback_fails(client, sample_interview):
    payload = {"score": 3.0, "recommendation": "yes"}
    first = client.post(f"/interviews/{sample_interview['id']}/feedback", json=payload)
    assert first.status_code == 201

    second = client.post(f"/interviews/{sample_interview['id']}/feedback", json=payload)
    assert second.status_code == 400


def test_get_feedback_not_found(client, sample_interview):
    resp = client.get(f"/interviews/{sample_interview['id']}/feedback")
    assert resp.status_code == 404


def test_feedback_score_out_of_range_rejected(client, sample_interview):
    resp = client.post(
        f"/interviews/{sample_interview['id']}/feedback",
        json={"score": 10.0, "recommendation": "yes"},
    )
    assert resp.status_code == 422
