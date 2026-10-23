"""
FastAPI router for the AI-Powered Resume Screening System.
Endpoints for automated candidate shortlisting, NLP skill extraction, and screening analytics.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import crud, models
from ..database import get_db
from ..resume_screener import (
    CANDIDATE_SKILL_PRESETS,
    SKILL_TAXONOMY,
    extract_skills_from_text,
    match_candidate_to_job,
    screen_candidates_for_job,
)

router = APIRouter(prefix="/screening", tags=["AI Resume Screening"])

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"


# ---------- Pydantic Schemas ----------

class ScreenRequest(BaseModel):
    job_id: Optional[int] = Field(None, description="Optional job ID from database")
    job_title: Optional[str] = Field("Software Engineer", description="Target job title")
    required_skills: List[str] = Field(..., min_length=1, description="List of mandatory technical skills")
    preferred_skills: Optional[List[str]] = Field(default=[], description="List of preferred/nice-to-have skills")
    min_experience_years: Optional[int] = Field(0, ge=0, le=40, description="Minimum years of experience")
    candidate_ids: Optional[List[int]] = Field(None, description="Optional subset of candidate IDs to screen")


class ExtractSkillsRequest(BaseModel):
    text: str = Field(..., min_length=5, description="Resume text or job description to extract skills from")


class ExtractSkillsResponse(BaseModel):
    skills: List[str]
    by_category: Dict[str, List[str]]
    total_skills_detected: int


# Default skill requirements map for quick presets
JOB_ROLE_SKILL_MAP: Dict[str, List[str]] = {
    "Backend Engineer": ["Python", "FastAPI", "PostgreSQL", "Docker", "REST APIs", "Git"],
    "Frontend Developer": ["JavaScript", "TypeScript", "React", "HTML/CSS", "Tailwind CSS", "Next.js"],
    "Full Stack Engineer": ["Python", "JavaScript", "TypeScript", "React", "PostgreSQL", "Docker", "REST APIs"],
    "DevOps Engineer": ["Docker", "Kubernetes", "AWS", "CI/CD", "Terraform", "Linux"],
    "AI / Data Scientist": ["Python", "Machine Learning", "PyTorch", "Pandas", "NumPy", "SQL", "Natural Language Processing (NLP)"],
    "Mobile Developer": ["Kotlin", "Swift", "React", "REST APIs", "Git"],
    "System Architect": ["System Design", "Microservices", "PostgreSQL", "Docker", "Kubernetes", "AWS"],
}


# ---------- Route Handlers ----------

@router.get("/taxonomy")
def get_skill_taxonomy():
    """Return the available industry skill taxonomy organized by category."""
    categories: Dict[str, List[str]] = {}
    for skill, data in SKILL_TAXONOMY.items():
        categories.setdefault(data["category"], []).append(skill)
    return {
        "total_skills": len(SKILL_TAXONOMY),
        "categories": categories,
    }


@router.get("/presets")
def get_job_presets(db: Session = Depends(get_db)):
    """Return existing jobs from database paired with recommended skill sets for 1-click screening."""
    db_jobs = crud.list_jobs(db, skip=0, limit=100)

    presets: List[Dict[str, Any]] = []
    for job in db_jobs:
        # Match preset by title keyword or default
        matched_skills = ["Python", "SQL", "Git", "REST APIs"]
        for role, skills in JOB_ROLE_SKILL_MAP.items():
            if any(term.lower() in job.title.lower() for term in role.split()):
                matched_skills = skills
                break

        # Also extract any skills mentioned directly in job description
        if job.description:
            desc_skills = extract_skills_from_text(job.description)["skills"]
            if desc_skills:
                matched_skills = sorted(set(matched_skills).union(desc_skills))

        presets.append({
            "id": job.id,
            "title": job.title,
            "department": job.department,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "recommended_skills": matched_skills,
        })

    # If no jobs exist, return default templates
    if not presets:
        for title, skills in JOB_ROLE_SKILL_MAP.items():
            presets.append({
                "id": None,
                "title": title,
                "department": "Engineering",
                "status": "open",
                "recommended_skills": skills,
            })

    return {"presets": presets}


@router.post("/extract-skills", response_model=ExtractSkillsResponse)
def extract_skills(payload: ExtractSkillsRequest):
    """Extract skills from raw resume or job description text using NLP."""
    result = extract_skills_from_text(payload.text)
    return ExtractSkillsResponse(
        skills=result["skills"],
        by_category=result["by_category"],
        total_skills_detected=len(result["skills"]),
    )


@router.post("/screen")
def screen_candidates(payload: ScreenRequest, db: Session = Depends(get_db)):
    """
    Run automated NLP screening, candidate ranking, and generate visual analytics.
    Evaluates candidate skills vs required/preferred skills and computes fit scores.
    """
    # 1. Fetch target candidates
    if payload.candidate_ids:
        candidates = [
            crud.get_candidate(db, cid)
            for cid in payload.candidate_ids
            if crud.get_candidate(db, cid) is not None
        ]
    else:
        candidates = crud.list_candidates(db, skip=0, limit=200)

    # If no candidates exist in database, create 4 realistic college demo candidate profiles
    if not candidates:
        demo_candidates = [
            models.Candidate(
                id=1,
                full_name="Aarav Sharma",
                email="aarav.sharma@example.com",
                phone="+91 98765 43210",
                resume_url="/uploads/resumes/aarav_backend.pdf",
            ),
            models.Candidate(
                id=2,
                full_name="Priya Patel",
                email="priya.patel@example.com",
                phone="+91 98765 43211",
                resume_url="/uploads/resumes/priya_fullstack.pdf",
            ),
            models.Candidate(
                id=3,
                full_name="Rohan Verma",
                email="rohan.verma@example.com",
                phone="+91 98765 43212",
                resume_url="/uploads/resumes/rohan_devops.pdf",
            ),
            models.Candidate(
                id=4,
                full_name="Sneha Rao",
                email="sneha.rao@example.com",
                phone="+91 98765 43213",
                resume_url="/uploads/resumes/sneha_frontend.pdf",
            ),
        ]
        candidates = demo_candidates

    # 2. Determine Job Title
    target_title = payload.job_title
    if payload.job_id:
        db_job = crud.get_job(db, payload.job_id)
        if db_job:
            target_title = db_job.title

    # 3. Execute NLP Screening Engine
    screening_result = screen_candidates_for_job(
        candidates=candidates,
        job_title=target_title or "Software Engineer",
        required_skills=payload.required_skills,
        preferred_skills=payload.preferred_skills,
        min_experience_years=payload.min_experience_years or 0,
        uploads_dir=UPLOAD_DIR,
    )

    return screening_result
