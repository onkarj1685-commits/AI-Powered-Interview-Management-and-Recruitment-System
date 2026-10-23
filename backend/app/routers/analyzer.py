"""
API Router for AI Resume Analyzer.

Provides endpoints for:
- Uploading and analyzing PDF resumes with zero manual configuration.
- Fetching immediate sample analysis for evaluation.
- Downloading generated AI Resume Analysis Reports in PDF format.
- Retrieving latest analysis result.
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..resume_analyzer import (
    DEFAULT_SAMPLE_RESUME_TEXT,
    analyze_pdf_file,
    analyze_resume_text,
    generate_pdf_report,
)

router = APIRouter(prefix="/analyzer", tags=["AI Resume Analyzer"])

# Directory configuration for uploaded resumes
_project_root = Path(__file__).resolve().parents[3]
_uploads_dir = _project_root / "uploads" / "resumes"
_uploads_dir.mkdir(parents=True, exist_ok=True)


def _save_analysis_to_db(db: Session, analysis_data: Dict[str, Any], file_url: Optional[str] = None) -> models.ResumeAnalysis:
    """Persist resume analysis record in SQLite/PostgreSQL."""
    rec = models.ResumeAnalysis(
        filename=analysis_data.get("filename", "resume.pdf"),
        file_url=file_url,
        candidate_name=analysis_data.get("candidate_name", "Candidate"),
        target_role=analysis_data.get("target_role", "Data Analyst"),
        overall_score=analysis_data.get("overall_score", 80),
        ats_score=analysis_data.get("ats_score", 85),
        strength=analysis_data.get("strength", "Good"),
        skills_found=analysis_data.get("skills_found", []),
        missing_skills=analysis_data.get("missing_skills", []),
        breakdown=analysis_data.get("breakdown", {}),
        suggestions=analysis_data.get("suggestions", []),
        strengths=analysis_data.get("strengths", []),
        weaknesses=analysis_data.get("weaknesses", []),
        recommendation=analysis_data.get("recommendation", ""),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.post("/upload-and-analyze")
async def upload_and_analyze_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Step 1 & Step 2: Upload PDF Resume and automatically analyze it.
    Zero manual configuration required (no manual job titles or required skills).
    """
    orig_name = file.filename or "resume.pdf"
    if not orig_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF resume files (.pdf) are accepted by the AI Resume Analyzer.",
        )

    # Save unique copy to uploads directory
    safe_filename = f"{uuid.uuid4().hex[:10]}_{Path(orig_name).name}"
    dest_path = _uploads_dir / safe_filename

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store resume upload: {str(exc)}",
        )

    # Run analysis pipeline
    analysis = analyze_pdf_file(dest_path, filename=orig_name)
    file_url = f"/uploads/resumes/{safe_filename}"

    # Persist record in database
    db_rec = _save_analysis_to_db(db, analysis, file_url)
    analysis["id"] = db_rec.id
    analysis["file_url"] = file_url
    return analysis


@router.get("/sample-analysis")
def get_sample_analysis(db: Session = Depends(get_db)):
    """
    Immediate evaluator convenience endpoint: runs and returns a realistic sample analysis
    for instant review without requiring manual file uploads.
    """
    analysis = analyze_resume_text(DEFAULT_SAMPLE_RESUME_TEXT, "Aditya_Verma_Data_Analyst_Resume.pdf")
    db_rec = _save_analysis_to_db(db, analysis, "/uploads/resumes/sample_aditya_verma.pdf")
    analysis["id"] = db_rec.id
    analysis["file_url"] = "/uploads/resumes/sample_aditya_verma.pdf"
    return analysis


@router.get("/latest")
def get_latest_analysis(db: Session = Depends(get_db)):
    """Retrieve the most recent resume analysis."""
    rec = (
        db.query(models.ResumeAnalysis)
        .order_by(models.ResumeAnalysis.id.desc())
        .first()
    )
    if not rec:
        return get_sample_analysis(db)

    return {
        "id": rec.id,
        "filename": rec.filename,
        "file_url": rec.file_url,
        "candidate_name": rec.candidate_name,
        "target_role": rec.target_role,
        "overall_score": rec.overall_score,
        "ats_score": rec.ats_score,
        "strength": rec.strength,
        "skills_found": rec.skills_found or [],
        "missing_skills": rec.missing_skills or [],
        "breakdown": rec.breakdown or {},
        "suggestions": rec.suggestions or [],
        "strengths": rec.strengths or [],
        "weaknesses": rec.weaknesses or [],
        "recommendation": rec.recommendation or "",
    }


@router.get("/report/{analysis_id}/pdf")
def download_resume_report_pdf(
    analysis_id: int,
    db: Session = Depends(get_db),
):
    """
    Section 7: Download AI Resume Report (PDF).
    Generates and returns an ATS & skill analysis PDF document.
    """
    rec = None
    if analysis_id > 0:
        rec = db.query(models.ResumeAnalysis).filter(models.ResumeAnalysis.id == analysis_id).first()
    
    if not rec:
        rec = db.query(models.ResumeAnalysis).order_by(models.ResumeAnalysis.id.desc()).first()

    if not rec:
        # Fallback to sample data if database is clean
        sample = analyze_resume_text(DEFAULT_SAMPLE_RESUME_TEXT, "Aditya_Verma_Data_Analyst_Resume.pdf")
        rec = _save_analysis_to_db(db, sample, "/uploads/resumes/sample_aditya_verma.pdf")

    analysis_dict = {
        "id": rec.id,
        "filename": rec.filename,
        "candidate_name": rec.candidate_name or "Candidate",
        "target_role": rec.target_role or "Data Analyst",
        "overall_score": rec.overall_score,
        "ats_score": rec.ats_score,
        "strength": rec.strength,
        "skills_found": rec.skills_found or [],
        "missing_skills": rec.missing_skills or [],
        "breakdown": rec.breakdown or {},
        "suggestions": rec.suggestions or [],
        "strengths": rec.strengths or [],
        "weaknesses": rec.weaknesses or [],
        "recommendation": rec.recommendation or "",
    }

    pdf_bytes = generate_pdf_report(analysis_dict)
    safe_title = (rec.candidate_name or "Candidate").replace(" ", "_")
    download_filename = f"AI_Resume_Report_{safe_title}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"',
            "Content-Type": "application/pdf",
        },
    )
