"""
Automated unit tests for NLP-based skill extraction and AI Resume Screening System.
"""
import pytest
from app.resume_screener import (
    extract_skills_from_text,
    extract_experience_years,
    match_candidate_to_job,
    screen_candidates_for_job,
)
from app import models


def test_extract_skills_nlp():
    """Verify n-gram and boundary matching across technical skills."""
    sample_text = """
    Senior Software Engineer with 5+ years of experience building scalable microservices.
    Proficient in Python, FastAPI, PostgreSQL, and Docker containerization.
    Familiar with AWS cloud (EC2, S3), CI/CD pipelines using GitHub Actions, and REST APIs.
    Strong background in Machine Learning, PyTorch, and System Design.
    """
    extracted = extract_skills_from_text(sample_text)
    skills = extracted["skills"]

    expected_skills = [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "AWS",
        "CI/CD",
        "REST APIs",
        "Microservices",
        "Machine Learning",
        "PyTorch",
        "System Design",
    ]
    for expected in expected_skills:
        assert expected in skills, f"Expected '{expected}' to be detected in extracted skills: {skills}"

    assert "Backend" in extracted["by_category"]
    assert "Cloud & DevOps" in extracted["by_category"]


def test_extract_experience_years():
    """Verify regex detection of years of experience."""
    t1 = "Senior Developer with 7+ years of experience in distributed systems."
    assert extract_experience_years(t1) == 7.0

    t2 = "Experience of 3.5 years in frontend React engineering."
    assert extract_experience_years(t2) == 3.5

    t3 = "Fresh graduate with no prior experience."
    assert extract_experience_years(t3) == 0.0


def test_match_candidate_scoring():
    """Verify scoring logic and recommendation tiering."""
    cand = models.Candidate(
        id=101,
        full_name="Grace Hopper",
        email="grace@navy.mil",
        resume_url=None,
    )
    custom_resume = """
    Lead Backend Architect with 8 years of experience.
    Core Skills: Python, FastAPI, PostgreSQL, Docker, Kubernetes, REST APIs, Microservices, System Design.
    """
    res = match_candidate_to_job(
        candidate=cand,
        job_title="Senior Backend Engineer",
        required_skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
        preferred_skills=["Kubernetes", "Microservices"],
        min_experience_years=5,
        custom_resume_text=custom_resume,
    )

    assert res["overall_score"] >= 80.0
    assert res["recommendation"] == "Strongly Shortlisted"
    assert "Python" in res["matched_skills"]
    assert "FastAPI" in res["matched_skills"]
    assert len(res["missing_skills"]) == 0
    assert len(res["strengths"]) > 0


def test_screening_endpoint_taxonomy(client):
    """Test /screening/taxonomy endpoint."""
    resp = client.get("/screening/taxonomy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_skills"] > 40
    assert "Languages" in data["categories"]
    assert "Cloud & DevOps" in data["categories"]


def test_screening_endpoint_extract_skills(client):
    """Test /screening/extract-skills endpoint."""
    resp = client.post(
        "/screening/extract-skills",
        json={"text": "Experienced in React, TypeScript, Tailwind CSS, and Next.js frontend development."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "React" in data["skills"]
    assert "TypeScript" in data["skills"]
    assert "Next.js" in data["skills"]
    assert data["total_skills_detected"] >= 3


def test_screening_endpoint_presets(client):
    """Test /screening/presets returns job presets with recommended skills."""
    resp = client.get("/screening/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert "presets" in data
    assert len(data["presets"]) > 0
    assert "recommended_skills" in data["presets"][0]


def test_screening_endpoint_screen_candidates(client):
    """Test full /screening/screen flow with candidates."""
    # Register 2 sample candidates
    client.post(
        "/candidates/",
        json={"full_name": "Dev One", "email": "dev1@test.com", "phone": "111-222"},
    )
    client.post(
        "/candidates/",
        json={"full_name": "Dev Two", "email": "dev2@test.com", "phone": "333-444"},
    )

    payload = {
        "job_title": "Backend Python Developer",
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "preferred_skills": ["Docker"],
        "min_experience_years": 2,
    }
    resp = client.post("/screening/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["job_title"] == "Backend Python Developer"
    assert "summary" in data
    assert data["summary"]["total_candidates"] >= 2
    assert "rankings" in data
    assert len(data["rankings"]) >= 2
    assert "analytics" in data
    assert "recommendation_distribution" in data["analytics"]
    assert "skill_coverage" in data["analytics"]
    assert "Python" in data["analytics"]["skill_coverage"]

    # Verify ranking order: descending by overall_score
    scores = [r["overall_score"] for r in data["rankings"]]
    assert scores == sorted(scores, reverse=True)
