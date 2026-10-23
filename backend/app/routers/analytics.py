"""
FastAPI Router for Recruitment Analytics and Hiring Insights.

Endpoints:
- GET /analytics/overview
- GET /analytics/recruitment-pipeline
- GET /analytics/interview-status
- GET /analytics/job-distribution
- GET /analytics/monthly-trends
- GET /analytics/interviewer-performance
- GET /analytics/recent-activity
- GET /analytics/interview-summary
- GET /analytics/job-summary
- GET /analytics/filters
- GET /analytics/export/csv
- GET /analytics/export/pdf
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import analytics_service
from .auth import require_current_user

router = APIRouter(prefix="/analytics", tags=["Recruitment Analytics"])


def require_hr_or_admin(user: models.User = Depends(require_current_user)) -> models.User:
    """Enforce that caller has HR, Administrator, or Recruiter privileges."""
    norm_role = (user.role or "").lower()
    if not any(r in norm_role for r in ["admin", "hr", "recruiter", "manager"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Recruitment analytics is restricted to HR and Admin roles.",
        )
    return user


@router.get("/filters", response_model=schemas.FilterOptionsOut)
@router.get("/filter-options", response_model=schemas.FilterOptionsOut)
def get_analytics_filter_options(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Retrieve available filter options for jobs, departments, interviewers, and statuses."""
    return analytics_service.get_filter_options(db, user=current_user)


@router.get("/filter-options/jobs")
@router.get("/filters/jobs")
def get_filter_jobs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Return list of distinct job positions for dropdowns."""
    opts = analytics_service.get_filter_options(db, user=current_user)
    return opts.jobs


@router.get("/filter-options/departments")
@router.get("/filters/departments")
def get_filter_departments(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Return list of distinct department names for dropdowns."""
    opts = analytics_service.get_filter_options(db, user=current_user)
    return opts.departments


@router.get("/filter-options/interviewers")
@router.get("/filters/interviewers")
def get_filter_interviewers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Return list of interviewers for dropdowns."""
    opts = analytics_service.get_filter_options(db, user=current_user)
    return opts.interviewers


@router.get("/overview", response_model=schemas.OverviewKPIsOut)
def get_overview_kpis(
    time_range: Optional[str] = Query("last_30_days", description="Preset: today, last_7_days, last_30_days, last_6_months, last_12_months, all, custom"),
    start_date: Optional[str] = Query(None, description="ISO/YYYY-MM-DD start date for custom range"),
    end_date: Optional[str] = Query(None, description="ISO/YYYY-MM-DD end date for custom range"),
    job_id: Optional[int] = Query(None, description="Filter by job position ID"),
    department: Optional[str] = Query(None, description="Filter by department"),
    interview_status: Optional[str] = Query(None, description="Filter by interview status"),
    candidate_stage: Optional[str] = Query(None, description="Filter by candidate stage"),
    interviewer_id: Optional[int] = Query(None, description="Filter by interviewer ID"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """
    Return high-level recruitment KPI cards:
    Total Candidates, Active Job Positions, Total Interviews,
    Interview Completion Rate, Average Feedback Score, and Selection Rate.
    """
    return analytics_service.get_overview_kpis(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/recruitment-pipeline", response_model=schemas.RecruitmentPipelineOut)
def get_recruitment_pipeline(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """
    Candidate distribution across stages:
    Applied -> Shortlisted -> Interview Scheduled -> Interviewed -> Selected -> Rejected.
    Includes stage percentages and cumulative funnel conversion.
    """
    return analytics_service.get_recruitment_pipeline(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/interview-status", response_model=schemas.InterviewStatusOut)
def get_interview_status(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Distribution of interviews by status: Scheduled, Completed, Cancelled, No Show."""
    return analytics_service.get_interview_status_distribution(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/job-distribution", response_model=schemas.JobDistributionOut)
def get_job_distribution(
    status_filter: Optional[str] = Query(None, description="Filter job position status (open, closed, on_hold)"),
    department_filter: Optional[str] = Query(None, description="Filter by department"),
    job_id: Optional[int] = Query(None, description="Filter by job position ID"),
    sort_order: Optional[str] = Query("highest", description="Sort by candidate count: highest, lowest, title"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Candidate distribution grouped by job positions with distinct applicant counting."""
    return analytics_service.get_job_wise_distribution(
        db=db,
        status_filter=status_filter,
        department_filter=department_filter,
        job_id=job_id,
        sort_order=sort_order or "highest",
        user=current_user,
    )


@router.get("/monthly-trends", response_model=schemas.MonthlyTrendsOut)
def get_monthly_trends(
    months: int = Query(6, ge=1, le=24, description="Number of months to analyze"),
    time_range: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """
    Monthly recruitment trends:
    candidates registered, interviews scheduled, interviews completed, and selections.
    Guarantees every month in range is present (0-activity months included).
    """
    return analytics_service.get_monthly_trends(
        db=db,
        months_count=months,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/interviewer-performance", response_model=schemas.InterviewerPerformanceOut)
def get_interviewer_performance(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """
    Interviewer workload & feedback scorecard:
    assigned interviews, completed, pending, feedback submission rate, and average score.
    """
    return analytics_service.get_interviewer_performance(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        interviewer_id=interviewer_id,
        job_id=job_id,
        department=department,
        user=current_user,
    )


@router.get("/recent-activity", response_model=schemas.RecentActivityOut)
def get_recent_activity(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    stage_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Paginated list of recent candidate recruitment activities."""
    return analytics_service.get_recent_activity(
        db=db,
        page=page,
        page_size=page_size,
        search=search,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        stage_filter=stage_filter,
        user=current_user,
    )


@router.get("/interview-summary", response_model=schemas.InterviewSummaryOut)
def get_interview_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    time_range: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Paginated list of interview summaries with status and score."""
    return analytics_service.get_interview_summary(
        db=db,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status_filter,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        user=current_user,
    )


@router.get("/job-summary", response_model=schemas.JobSummaryOut)
def get_job_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Paginated job positions summary with candidates and interviews counts."""
    return analytics_service.get_job_summary(
        db=db,
        page=page,
        page_size=page_size,
        search=search,
        job_id=job_id,
        department=department,
        user=current_user,
    )


@router.get("/export/csv")
def export_analytics_csv(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interview_status: Optional[str] = Query(None),
    candidate_stage: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Export filtered recruitment analytics dataset as CSV (UTF-8 with BOM)."""
    csv_content = analytics_service.generate_analytics_csv(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=current_user,
    )

    filename = f"recruitment_analytics_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    # Prepend UTF-8 BOM so Microsoft Excel correctly displays accents and UTF-8 characters
    csv_bytes = "\ufeff".encode("utf-8") + csv_content.encode("utf-8")

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/export/pdf")
def export_analytics_pdf(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interview_status: Optional[str] = Query(None),
    candidate_stage: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Generate executive recruitment analytics PDF report."""
    pdf_bytes = analytics_service.generate_analytics_pdf(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=current_user,
    )

    filename = f"recruitment_analytics_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ---------- Aliases & Specialized Analysis Endpoints ----------

@router.get("/summary", response_model=schemas.OverviewKPIsOut)
def get_analytics_summary(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interview_status: Optional[str] = Query(None),
    candidate_stage: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Alias for /analytics/overview."""
    return analytics_service.get_overview_kpis(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/recruitment-funnel", response_model=schemas.RecruitmentPipelineOut)
def get_recruitment_funnel(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Alias for /analytics/recruitment-pipeline."""
    return analytics_service.get_recruitment_pipeline(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        user=current_user,
    )


@router.get("/recruitment-trends", response_model=schemas.MonthlyTrendsOut)
def get_recruitment_trends(
    months: int = Query(6, ge=1, le=24),
    time_range: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Alias for /analytics/monthly-trends."""
    return analytics_service.get_monthly_trends(
        db=db,
        months_count=months,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=current_user,
    )


@router.get("/interviewer-workload", response_model=schemas.InterviewerPerformanceOut)
def get_interviewer_workload(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Alias for /analytics/interviewer-performance."""
    return analytics_service.get_interviewer_performance(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        interviewer_id=interviewer_id,
        job_id=job_id,
        department=department,
        user=current_user,
    )


@router.get("/feedback-analysis", response_model=schemas.FeedbackAnalysisOut)
def get_feedback_analysis(
    time_range: Optional[str] = Query("last_30_days"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    job_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    interviewer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_hr_or_admin),
):
    """Retrieve score distribution by tiers (1.0-2.0, 2.1-3.0, 3.1-4.0, 4.1-5.0) and overall average."""
    return analytics_service.get_feedback_analysis(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=current_user,
    )
