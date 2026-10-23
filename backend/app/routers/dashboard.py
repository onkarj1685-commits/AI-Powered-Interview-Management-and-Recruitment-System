"""
Dashboard statistics endpoint.

Returns aggregate KPIs and recent activity for the frontend dashboard view.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from .. import models

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Return aggregate hiring-pipeline statistics for the dashboard."""

    total_candidates = db.query(func.count(models.Candidate.id)).scalar() or 0
    total_jobs = db.query(func.count(models.JobPosition.id)).scalar() or 0
    total_interviewers = db.query(func.count(models.Interviewer.id)).scalar() or 0
    total_interviews = db.query(func.count(models.Interview.id)).scalar() or 0

    # --- Interviews grouped by status ---
    interviews_by_status = {}
    for status in models.InterviewStatus:
        count = (
            db.query(func.count(models.Interview.id))
            .filter(models.Interview.status == status)
            .scalar()
        )
        interviews_by_status[status.value] = count or 0

    # --- Jobs grouped by status ---
    jobs_by_status = {}
    for status in models.JobStatus:
        count = (
            db.query(func.count(models.JobPosition.id))
            .filter(models.JobPosition.status == status)
            .scalar()
        )
        jobs_by_status[status.value] = count or 0

    # --- Average feedback score ---
    avg_score = db.query(func.avg(models.Feedback.score)).scalar()

    # --- Five most recent interviews with nested names ---
    recent = (
        db.query(models.Interview)
        .order_by(models.Interview.scheduled_at.desc())
        .limit(5)
        .all()
    )

    recent_interviews = []
    for iv in recent:
        recent_interviews.append(
            {
                "id": iv.id,
                "candidate_name": iv.candidate.full_name if iv.candidate else "Unknown",
                "job_title": iv.job.title if iv.job else "Unknown",
                "interviewer_name": iv.interviewer.full_name if iv.interviewer else "Unknown",
                "scheduled_at": iv.scheduled_at.isoformat() if iv.scheduled_at else None,
                "status": iv.status.value,
                "round_name": iv.round_name,
            }
        )

    return {
        "total_candidates": total_candidates,
        "total_jobs": total_jobs,
        "total_interviewers": total_interviewers,
        "total_interviews": total_interviews,
        "interviews_by_status": interviews_by_status,
        "jobs_by_status": jobs_by_status,
        "average_score": round(avg_score, 1) if avg_score else None,
        "recent_interviews": recent_interviews,
    }
