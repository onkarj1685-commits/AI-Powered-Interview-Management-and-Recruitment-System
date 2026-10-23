"""
Recruitment Analytics and Hiring Insights Service Layer.

Provides data aggregation, KPI computations, monthly trend calculations,
interviewer performance metrics, and CSV/PDF export generation.
"""
import calendar
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException, status
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import and_, distinct, func, or_
from sqlalchemy.orm import Session

from .. import models, schemas


# =============================================================================
# 1. Date Range & Filter Normalization
# =============================================================================

def parse_date_range(
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[datetime, datetime, Optional[datetime], Optional[datetime], str]:
    """
    Parse and validate incoming date filter parameters.
    Returns:
        (current_start, current_end, previous_start, previous_end, period_label)
    All datetimes are timezone-naive UTC for consistent database comparisons.
    """
    now = datetime.utcnow()

    # Custom date range
    if time_range == "custom" or (start_date and end_date):
        if not start_date or not end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both start_date and end_date are required for custom date ranges.",
            )
        try:
            # Support both YYYY-MM-DD and full ISO strings
            if "T" in start_date:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            else:
                start_dt = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d")
            
            if "T" in end_date:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            else:
                end_dt = datetime.strptime(end_date.strip()[:10], "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Expected YYYY-MM-DD or ISO 8601 string.",
            )

        if start_dt > end_dt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date range: start_date cannot be after end_date.",
            )

        duration = end_dt - start_dt
        prev_end = start_dt - timedelta(microseconds=1)
        prev_start = prev_end - duration
        label = f"{start_dt.strftime('%b %d, %Y')} – {end_dt.strftime('%b %d, %Y')}"
        return start_dt, end_dt, prev_start, prev_end, label

    # Preset time ranges
    if time_range == "today":
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        prev_start = start_dt - timedelta(days=1)
        prev_end = end_dt - timedelta(days=1)
        label = f"Today ({now.strftime('%b %d, %Y')})"
    elif time_range == "last_7_days":
        start_dt = now - timedelta(days=7)
        end_dt = now
        prev_start = start_dt - timedelta(days=7)
        prev_end = start_dt
        label = "Last 7 Days"
    elif time_range == "last_6_months":
        start_dt = now - timedelta(days=180)
        end_dt = now
        prev_start = start_dt - timedelta(days=180)
        prev_end = start_dt
        label = "Last 6 Months"
    elif time_range == "last_12_months":
        start_dt = now - timedelta(days=365)
        end_dt = now
        prev_start = start_dt - timedelta(days=365)
        prev_end = start_dt
        label = "Last 12 Months"
    elif time_range == "all":
        start_dt = datetime(2020, 1, 1, 0, 0, 0)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        prev_start = None
        prev_end = None
        label = "All Time"
    else:
        # Default: last_30_days
        start_dt = now - timedelta(days=30)
        end_dt = now
        prev_start = start_dt - timedelta(days=30)
        prev_end = start_dt
        label = "Last 30 Days"

    return start_dt, end_dt, prev_start, prev_end, label


def build_comparison_kpi(
    label: str,
    current_val: Union[int, float],
    previous_val: Optional[Union[int, float]],
    display_format: str = "number",
    subtext: Optional[str] = None,
    tooltip: str = "",
    higher_is_better: bool = True,
) -> schemas.KPIItem:
    """Helper to construct a KPI item with period comparison calculation."""
    if display_format == "percentage":
        display_str = f"{current_val:.1f}%"
    elif display_format == "score":
        display_str = f"{current_val:.1f} / 5.0" if current_val is not None else "—"
    else:
        display_str = f"{current_val:,}" if isinstance(current_val, int) else f"{current_val:.1f}"

    if previous_val is None or previous_val == 0:
        if previous_val == 0 and current_val > 0:
            pct_change = 100.0
            comparison_text = "+100% vs previous period"
            trend = "up"
        elif previous_val == 0 and current_val == 0:
            pct_change = 0.0
            comparison_text = "No change vs previous period"
            trend = "neutral"
        else:
            pct_change = None
            comparison_text = "No previous-period data"
            trend = "neutral"
    else:
        pct_change = round(((current_val - previous_val) / previous_val) * 100, 1)
        sign = "+" if pct_change > 0 else ""
        comparison_text = f"{sign}{pct_change}% vs previous period"
        if pct_change > 0:
            trend = "up" if higher_is_better else "down"
        elif pct_change < 0:
            trend = "down" if higher_is_better else "up"
        else:
            trend = "neutral"

    return schemas.KPIItem(
        value=current_val,
        display_value=display_str,
        label=label,
        subtext=subtext,
        previous_period_value=previous_val,
        percentage_change=pct_change,
        comparison_text=comparison_text,
        trend=trend,
        tooltip=tooltip,
    )


# =============================================================================
# 2. Recruitment KPI Cards (Overview)
# =============================================================================

def get_overview_kpis(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interview_status: Optional[str] = None,
    candidate_stage: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> schemas.OverviewKPIsOut:
    """Compute top-level recruitment KPI cards with comparison to previous period."""
    curr_start, curr_end, prev_start, prev_end, period_label = parse_date_range(
        time_range, start_date, end_date
    )

    # -------------------------------------------------------------
    # A. Total Candidates
    # -------------------------------------------------------------
    cand_query = db.query(distinct(models.Candidate.id))
    if job_id:
        cand_query = cand_query.outerjoin(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
            or_(models.Candidate.job_id == job_id, models.Interview.job_id == job_id)
        )
    if department:
        cand_query = cand_query.outerjoin(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        cand_query = cand_query.join(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
            models.Interview.interviewer_id == interviewer_id
        )
    total_candidates_all_time = cand_query.count()

    # Period registrations
    cand_period_curr = db.query(models.Candidate.id).filter(
        models.Candidate.created_at >= curr_start,
        models.Candidate.created_at <= curr_end,
    )
    if job_id:
        cand_period_curr = cand_period_curr.filter(models.Candidate.job_id == job_id)
    if department:
        cand_period_curr = cand_period_curr.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        cand_period_curr = cand_period_curr.join(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
            models.Interview.interviewer_id == interviewer_id
        )
    curr_candidates_count = cand_period_curr.count()

    prev_candidates_count = None
    if prev_start and prev_end:
        cand_period_prev = db.query(models.Candidate.id).filter(
            models.Candidate.created_at >= prev_start,
            models.Candidate.created_at <= prev_end,
        )
        if job_id:
            cand_period_prev = cand_period_prev.filter(models.Candidate.job_id == job_id)
        if department:
            cand_period_prev = cand_period_prev.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            cand_period_prev = cand_period_prev.join(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
                models.Interview.interviewer_id == interviewer_id
            )
        prev_candidates_count = cand_period_prev.count()

    kpi_candidates = build_comparison_kpi(
        label="Total Candidates",
        current_val=curr_candidates_count,
        previous_val=prev_candidates_count,
        display_format="number",
        subtext=f"{total_candidates_all_time} total registered in system",
        tooltip="Candidates registered in the selected period and total count in system.",
    )

    # -------------------------------------------------------------
    # B. Active Job Positions
    # -------------------------------------------------------------
    job_query = db.query(models.JobPosition)
    if job_id:
        job_query = job_query.filter(models.JobPosition.id == job_id)
    if department:
        job_query = job_query.filter(func.trim(func.lower(models.JobPosition.department)) == department.strip().lower())
    total_jobs = job_query.count()
    active_jobs = job_query.filter(models.JobPosition.status == models.JobStatus.OPEN).count()

    # Previous active jobs (using created_at boundary)
    prev_active_jobs = None
    if prev_start and prev_end:
        prev_active_jobs = (
            db.query(models.JobPosition)
            .filter(
                models.JobPosition.status == models.JobStatus.OPEN,
                models.JobPosition.created_at <= prev_end,
            )
            .count()
        )

    kpi_jobs = build_comparison_kpi(
        label="Active Job Positions",
        current_val=active_jobs,
        previous_val=prev_active_jobs,
        display_format="number",
        subtext=f"{total_jobs} total positions posted",
        tooltip="Open job roles currently accepting applications.",
    )

    # -------------------------------------------------------------
    # C. Total Interviews
    # -------------------------------------------------------------
    iv_curr = db.query(models.Interview).filter(
        models.Interview.scheduled_at >= curr_start,
        models.Interview.scheduled_at <= curr_end,
    )
    if job_id:
        iv_curr = iv_curr.filter(models.Interview.job_id == job_id)
    if department:
        iv_curr = iv_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        iv_curr = iv_curr.filter(models.Interview.interviewer_id == interviewer_id)
    if interview_status:
        iv_curr = iv_curr.filter(models.Interview.status == interview_status.lower().strip())

    curr_interviews_count = iv_curr.count()

    prev_interviews_count = None
    if prev_start and prev_end:
        iv_prev = db.query(models.Interview).filter(
            models.Interview.scheduled_at >= prev_start,
            models.Interview.scheduled_at <= prev_end,
        )
        if job_id:
            iv_prev = iv_prev.filter(models.Interview.job_id == job_id)
        if department:
            iv_prev = iv_prev.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            iv_prev = iv_prev.filter(models.Interview.interviewer_id == interviewer_id)
        if interview_status:
            iv_prev = iv_prev.filter(models.Interview.status == interview_status.lower().strip())
        prev_interviews_count = iv_prev.count()

    kpi_interviews = build_comparison_kpi(
        label="Total Interviews",
        current_val=curr_interviews_count,
        previous_val=prev_interviews_count,
        display_format="number",
        subtext="Scheduled, completed, or cancelled in period",
        tooltip="Interviews scheduled within the selected date range.",
    )

    # -------------------------------------------------------------
    # D. Interview Completion Rate
    # Formula: Completed / (Completed + Cancelled + No Show) * 100
    # Scheduled (upcoming) interviews are excluded from the denominator.
    # -------------------------------------------------------------
    completed_curr = (
        db.query(models.Interview)
        .filter(
            models.Interview.scheduled_at >= curr_start,
            models.Interview.scheduled_at <= curr_end,
            models.Interview.status == models.InterviewStatus.COMPLETED,
        )
    )
    if job_id:
        completed_curr = completed_curr.filter(models.Interview.job_id == job_id)
    if department:
        completed_curr = completed_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        completed_curr = completed_curr.filter(models.Interview.interviewer_id == interviewer_id)
    curr_completed_count = completed_curr.count()

    concluded_curr = (
        db.query(models.Interview)
        .filter(
            models.Interview.scheduled_at >= curr_start,
            models.Interview.scheduled_at <= curr_end,
            models.Interview.status.in_([
                models.InterviewStatus.COMPLETED,
                models.InterviewStatus.CANCELLED,
                models.InterviewStatus.NO_SHOW,
            ]),
        )
    )
    if job_id:
        concluded_curr = concluded_curr.filter(models.Interview.job_id == job_id)
    if department:
        concluded_curr = concluded_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        concluded_curr = concluded_curr.filter(models.Interview.interviewer_id == interviewer_id)
    curr_concluded_count = concluded_curr.count()

    curr_comp_rate = (
        round((curr_completed_count / curr_concluded_count) * 100, 1)
        if curr_concluded_count > 0
        else 0.0
    )

    prev_comp_rate = None
    if prev_start and prev_end:
        prev_comp_q = (
            db.query(models.Interview)
            .filter(
                models.Interview.scheduled_at >= prev_start,
                models.Interview.scheduled_at <= prev_end,
                models.Interview.status == models.InterviewStatus.COMPLETED,
            )
        )
        if job_id:
            prev_comp_q = prev_comp_q.filter(models.Interview.job_id == job_id)
        if department:
            prev_comp_q = prev_comp_q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            prev_comp_q = prev_comp_q.filter(models.Interview.interviewer_id == interviewer_id)
        prev_comp = prev_comp_q.count()

        prev_conc_q = (
            db.query(models.Interview)
            .filter(
                models.Interview.scheduled_at >= prev_start,
                models.Interview.scheduled_at <= prev_end,
                models.Interview.status.in_([
                    models.InterviewStatus.COMPLETED,
                    models.InterviewStatus.CANCELLED,
                    models.InterviewStatus.NO_SHOW,
                ]),
            )
        )
        if job_id:
            prev_conc_q = prev_conc_q.filter(models.Interview.job_id == job_id)
        if department:
            prev_conc_q = prev_conc_q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            prev_conc_q = prev_conc_q.filter(models.Interview.interviewer_id == interviewer_id)
        prev_conc = prev_conc_q.count()
        if prev_conc > 0:
            prev_comp_rate = round((prev_comp / prev_conc) * 100, 1)

    kpi_completion_rate = build_comparison_kpi(
        label="Interview Completion Rate",
        current_val=curr_comp_rate,
        previous_val=prev_comp_rate,
        display_format="percentage",
        subtext=f"{curr_completed_count} of {curr_concluded_count} eligible interviews",
        tooltip="Completed Interviews / Total Eligible Interviews (Completed + Cancelled + No Show) × 100. Pending scheduled interviews are excluded from the denominator.",
    )

    # -------------------------------------------------------------
    # E. Average Interview Feedback Score (Scale: 1.0 - 5.0)
    # -------------------------------------------------------------
    score_query_curr = (
        db.query(func.avg(models.Feedback.score), func.count(models.Feedback.id))
        .join(models.Interview, models.Feedback.interview_id == models.Interview.id)
        .filter(
            models.Interview.scheduled_at >= curr_start,
            models.Interview.scheduled_at <= curr_end,
            models.Feedback.score.isnot(None),
        )
    )
    if job_id:
        score_query_curr = score_query_curr.filter(models.Interview.job_id == job_id)
    if department:
        score_query_curr = score_query_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        score_query_curr = score_query_curr.filter(models.Interview.interviewer_id == interviewer_id)

    curr_avg_score_raw, curr_score_count = score_query_curr.first() or (None, 0)
    curr_avg_score = round(curr_avg_score_raw, 2) if curr_avg_score_raw is not None else 0.0

    prev_avg_score = None
    if prev_start and prev_end:
        prev_res_q = (
            db.query(func.avg(models.Feedback.score))
            .join(models.Interview, models.Feedback.interview_id == models.Interview.id)
            .filter(
                models.Interview.scheduled_at >= prev_start,
                models.Interview.scheduled_at <= prev_end,
                models.Feedback.score.isnot(None),
            )
        )
        if job_id:
            prev_res_q = prev_res_q.filter(models.Interview.job_id == job_id)
        if department:
            prev_res_q = prev_res_q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            prev_res_q = prev_res_q.filter(models.Interview.interviewer_id == interviewer_id)
        prev_res = prev_res_q.scalar()
        if prev_res is not None:
            prev_avg_score = round(prev_res, 2)

    kpi_score = build_comparison_kpi(
        label="Avg Feedback Score",
        current_val=curr_avg_score if curr_score_count > 0 else 0.0,
        previous_val=prev_avg_score,
        display_format="score",
        subtext=f"{curr_score_count} submitted scorecard{'s' if curr_score_count != 1 else ''}",
        tooltip="Average rating given by interviewers (Score scale 1.0 - 5.0). Null and missing scores are excluded.",
    )

    # -------------------------------------------------------------
    # F. Selection Rate
    # Formula: Selected Candidates / Total Candidates × 100
    # -------------------------------------------------------------
    total_cand_period = curr_candidates_count if curr_candidates_count > 0 else total_candidates_all_time
    selected_curr = db.query(models.Candidate.id).filter(
        models.Candidate.status.ilike("selected"),
    )
    if job_id:
        selected_curr = selected_curr.filter(models.Candidate.job_id == job_id)
    if department:
        selected_curr = selected_curr.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        selected_curr = selected_curr.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
            models.Interview.interviewer_id == interviewer_id
        )
    curr_selected_count = selected_curr.count()

    curr_selection_rate = (
        round((curr_selected_count / total_cand_period) * 100, 1)
        if total_cand_period > 0
        else 0.0
    )

    prev_selection_rate = None
    if prev_candidates_count and prev_candidates_count > 0:
        prev_sel_q = (
            db.query(models.Candidate.id)
            .filter(
                models.Candidate.status.ilike("selected"),
                models.Candidate.created_at <= prev_end,
            )
        )
        if job_id:
            prev_sel_q = prev_sel_q.filter(models.Candidate.job_id == job_id)
        if department:
            prev_sel_q = prev_sel_q.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            prev_sel_q = prev_sel_q.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
                models.Interview.interviewer_id == interviewer_id
            )
        prev_sel_count = prev_sel_q.count()
        prev_selection_rate = round((prev_sel_count / prev_candidates_count) * 100, 1)

    kpi_selection_rate = build_comparison_kpi(
        label="Selection Rate",
        current_val=curr_selection_rate,
        previous_val=prev_selection_rate,
        display_format="percentage",
        subtext=f"{curr_selected_count} selected candidate{'s' if curr_selected_count != 1 else ''}",
        tooltip="Percentage of unique candidates who reached the Selected hiring stage. Formula: Selected / Total Unique Candidates × 100.",
    )

    # -------------------------------------------------------------
    # G. Cancelled Interviews
    # -------------------------------------------------------------
    canc_curr = db.query(models.Interview).filter(
        models.Interview.scheduled_at >= curr_start,
        models.Interview.scheduled_at <= curr_end,
        models.Interview.status == models.InterviewStatus.CANCELLED,
    )
    if job_id:
        canc_curr = canc_curr.filter(models.Interview.job_id == job_id)
    if department:
        canc_curr = canc_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        canc_curr = canc_curr.filter(models.Interview.interviewer_id == interviewer_id)
    curr_cancelled_count = canc_curr.count()

    prev_cancelled_count = None
    if prev_start and prev_end:
        canc_prev = db.query(models.Interview).filter(
            models.Interview.scheduled_at >= prev_start,
            models.Interview.scheduled_at <= prev_end,
            models.Interview.status == models.InterviewStatus.CANCELLED,
        )
        if job_id:
            canc_prev = canc_prev.filter(models.Interview.job_id == job_id)
        if department:
            canc_prev = canc_prev.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            canc_prev = canc_prev.filter(models.Interview.interviewer_id == interviewer_id)
        prev_cancelled_count = canc_prev.count()

    kpi_cancelled = build_comparison_kpi(
        label="Cancelled Interviews",
        current_val=curr_cancelled_count,
        previous_val=prev_cancelled_count,
        display_format="number",
        subtext=f"{curr_cancelled_count} interview{'s' if curr_cancelled_count != 1 else ''} cancelled",
        tooltip="Total scheduled interviews that were cancelled by candidates or interviewers.",
        higher_is_better=False,
    )

    # -------------------------------------------------------------
    # H. Candidates Hired
    # -------------------------------------------------------------
    hired_curr = db.query(models.Candidate).filter(
        models.Candidate.status.ilike("selected"),
    )
    if job_id:
        hired_curr = hired_curr.filter(models.Candidate.job_id == job_id)
    if department:
        hired_curr = hired_curr.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        hired_curr = hired_curr.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
            models.Interview.interviewer_id == interviewer_id
        )
    hired_curr = hired_curr.filter(
        or_(
            and_(models.Candidate.selection_timestamp.isnot(None), models.Candidate.selection_timestamp >= curr_start, models.Candidate.selection_timestamp <= curr_end),
            and_(models.Candidate.selection_timestamp.is_(None), models.Candidate.created_at >= curr_start, models.Candidate.created_at <= curr_end),
        )
    )
    curr_hired_count = hired_curr.count()

    prev_hired_count = None
    if prev_start and prev_end:
        hired_prev = db.query(models.Candidate).filter(
            models.Candidate.status.ilike("selected"),
            models.Candidate.created_at <= prev_end,
        )
        if job_id:
            hired_prev = hired_prev.filter(models.Candidate.job_id == job_id)
        if department:
            hired_prev = hired_prev.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            hired_prev = hired_prev.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
                models.Interview.interviewer_id == interviewer_id
            )
        prev_hired_count = hired_prev.count()

    kpi_hired = build_comparison_kpi(
        label="Candidates Hired",
        current_val=curr_hired_count,
        previous_val=prev_hired_count,
        display_format="number",
        subtext=f"{curr_hired_count} candidate{'s' if curr_hired_count != 1 else ''} confirmed hired",
        tooltip="Candidates reaching the final Selected/Hired stage in this period.",
        higher_is_better=True,
    )

    # -------------------------------------------------------------
    # I. Pending Interviews
    # -------------------------------------------------------------
    pend_curr = db.query(models.Interview).filter(
        models.Interview.scheduled_at >= curr_start,
        models.Interview.scheduled_at <= curr_end,
        models.Interview.status == models.InterviewStatus.SCHEDULED,
    )
    if job_id:
        pend_curr = pend_curr.filter(models.Interview.job_id == job_id)
    if department:
        pend_curr = pend_curr.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        pend_curr = pend_curr.filter(models.Interview.interviewer_id == interviewer_id)
    curr_pending_count = pend_curr.count()

    prev_pending_count = None
    if prev_start and prev_end:
        pend_prev = db.query(models.Interview).filter(
            models.Interview.scheduled_at >= prev_start,
            models.Interview.scheduled_at <= prev_end,
            models.Interview.status == models.InterviewStatus.SCHEDULED,
        )
        if job_id:
            pend_prev = pend_prev.filter(models.Interview.job_id == job_id)
        if department:
            pend_prev = pend_prev.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            pend_prev = pend_prev.filter(models.Interview.interviewer_id == interviewer_id)
        prev_pending_count = pend_prev.count()

    kpi_pending = build_comparison_kpi(
        label="Pending Interviews",
        current_val=curr_pending_count,
        previous_val=prev_pending_count,
        display_format="number",
        subtext=f"{curr_pending_count} upcoming appointment{'s' if curr_pending_count != 1 else ''}",
        tooltip="Interviews currently scheduled and awaiting execution.",
        higher_is_better=False,
    )

    return schemas.OverviewKPIsOut(
        total_candidates=kpi_candidates,
        active_jobs=kpi_jobs,
        total_interviews=kpi_interviews,
        completion_rate=kpi_completion_rate,
        avg_feedback_score=kpi_score,
        cancelled_interviews=kpi_cancelled,
        candidates_hired=kpi_hired,
        pending_interviews=kpi_pending,
        selection_rate=kpi_selection_rate,
        filter_summary={
            "period_label": period_label,
            "start_date": curr_start.isoformat(),
            "end_date": curr_end.isoformat(),
            "job_id": job_id,
            "department": department,
            "interview_status": interview_status,
            "candidate_stage": candidate_stage,
            "interviewer_id": interviewer_id,
        },
    )


# =============================================================================
# 3. Candidate Recruitment Pipeline Funnel
# =============================================================================

def get_recruitment_pipeline(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> schemas.RecruitmentPipelineOut:
    """
    Calculate candidate distribution across pipeline stages:
    Applied -> Shortlisted -> Interview Scheduled -> Interviewed -> Selected -> Rejected.
    Provides both mutually exclusive stage counts and cumulative funnel progression.
    """
    curr_start, curr_end, _, _, _ = parse_date_range(time_range, start_date, end_date)

    # Base candidate query
    cand_query = db.query(models.Candidate)
    if job_id:
        cand_query = cand_query.outerjoin(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
            or_(models.Candidate.job_id == job_id, models.Interview.job_id == job_id)
        )
    if department:
        cand_query = cand_query.outerjoin(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        cand_query = cand_query.join(models.Interview, models.Interview.candidate_id == models.Candidate.id).filter(
            models.Interview.interviewer_id == interviewer_id
        )

    candidates = cand_query.all()
    total_candidates = len(candidates)

    if total_candidates == 0:
        empty_stages = [
            schemas.PipelineStageItem(stage_key="applied", stage_label="Applied", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
            schemas.PipelineStageItem(stage_key="shortlisted", stage_label="Shortlisted", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
            schemas.PipelineStageItem(stage_key="interview_scheduled", stage_label="Interview Scheduled", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
            schemas.PipelineStageItem(stage_key="interviewed", stage_label="Interviewed", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
            schemas.PipelineStageItem(stage_key="selected", stage_label="Selected", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
            schemas.PipelineStageItem(stage_key="rejected", stage_label="Rejected", count=0, percentage=0.0, funnel_count=0, funnel_percentage=0.0),
        ]
        return schemas.RecruitmentPipelineOut(stages=empty_stages, total_candidates=0)

    # Categorize candidates based on status and interview history
    applied_count = 0
    shortlisted_count = 0
    scheduled_count = 0
    interviewed_count = 0
    selected_count = 0
    rejected_count = 0

    # Cumulative milestones
    funnel_applied = total_candidates
    funnel_shortlisted = 0
    funnel_scheduled = 0
    funnel_interviewed = 0
    funnel_selected = 0

    for cand in candidates:
        st = (cand.status or "applied").lower().strip()
        interviews = cand.interviews or []
        has_completed_interview = any(iv.status == models.InterviewStatus.COMPLETED for iv in interviews)
        has_scheduled_interview = any(iv.status == models.InterviewStatus.SCHEDULED for iv in interviews)

        # Cumulative checks
        is_shortlisted = st in ["shortlisted", "selected"] or bool(interviews)
        if is_shortlisted:
            funnel_shortlisted += 1
        if has_scheduled_interview or has_completed_interview:
            funnel_scheduled += 1
        if has_completed_interview:
            funnel_interviewed += 1
        if st == "selected":
            funnel_selected += 1

        # Mutually exclusive current stage determination
        if st == "selected":
            selected_count += 1
        elif st == "rejected":
            rejected_count += 1
        elif has_completed_interview:
            interviewed_count += 1
        elif has_scheduled_interview:
            scheduled_count += 1
        elif st == "shortlisted":
            shortlisted_count += 1
        else:
            applied_count += 1

    stage_definitions = [
        ("applied", "Applied", applied_count, funnel_applied),
        ("shortlisted", "Shortlisted", shortlisted_count, funnel_shortlisted),
        ("interview_scheduled", "Interview Scheduled", scheduled_count, funnel_scheduled),
        ("interviewed", "Interviewed", interviewed_count, funnel_interviewed),
        ("selected", "Selected", selected_count, funnel_selected),
        ("rejected", "Rejected", rejected_count, rejected_count),
    ]

    pipeline_stages = []
    for key, label, count, f_count in stage_definitions:
        pct = round((count / total_candidates) * 100, 1) if total_candidates > 0 else 0.0
        f_pct = round((f_count / total_candidates) * 100, 1) if total_candidates > 0 else 0.0
        pipeline_stages.append(
            schemas.PipelineStageItem(
                stage_key=key,
                stage_label=label,
                count=count,
                percentage=pct,
                funnel_count=f_count,
                funnel_percentage=f_pct,
            )
        )

    return schemas.RecruitmentPipelineOut(
        stages=pipeline_stages,
        total_candidates=total_candidates,
    )


# =============================================================================
# 4. Interview Status Analytics
# =============================================================================

def get_interview_status_distribution(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> schemas.InterviewStatusOut:
    """Calculate distribution of interviews by status with percentages and standard colors."""
    curr_start, curr_end, _, _, _ = parse_date_range(time_range, start_date, end_date)

    query = db.query(models.Interview.status, func.count(models.Interview.id)).filter(
        models.Interview.scheduled_at >= curr_start,
        models.Interview.scheduled_at <= curr_end,
    )
    if job_id:
        query = query.filter(models.Interview.job_id == job_id)
    if department:
        query = query.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        query = query.filter(models.Interview.interviewer_id == interviewer_id)

    status_counts = dict(query.group_by(models.Interview.status).all())
    total_interviews = sum(status_counts.values())

    status_meta = [
        ("scheduled", "Scheduled", "#D97706"),   # Amber
        ("completed", "Completed", "#059669"),   # Emerald
        ("cancelled", "Cancelled", "#DC2626"),   # Red
        ("no_show", "No Show", "#BE123C"),       # Crimson
    ]

    result_items = []
    for key, label, color in status_meta:
        enum_val = getattr(models.InterviewStatus, key.upper(), None)
        cnt = status_counts.get(enum_val, 0) if enum_val else status_counts.get(key, 0)
        pct = round((cnt / total_interviews) * 100, 1) if total_interviews > 0 else 0.0
        result_items.append(
            schemas.InterviewStatusItem(
                status_key=key,
                status_label=label,
                count=cnt,
                percentage=pct,
                color=color,
            )
        )

    return schemas.InterviewStatusOut(
        statuses=result_items,
        total_interviews=total_interviews,
    )


# =============================================================================
# 5. Job-Wise Candidate Distribution
# =============================================================================

def get_job_wise_distribution(
    db: Session,
    status_filter: Optional[str] = None,
    department_filter: Optional[str] = None,
    job_id: Optional[int] = None,
    sort_order: str = "highest",  # "highest", "lowest", "title"
    user: Optional[models.User] = None,
) -> schemas.JobDistributionOut:
    """
    Calculate unique candidates associated with each job position.
    Correctly counts candidates having direct job_id or interviews for the job,
    preventing duplicate counts with DISTINCT aggregations.
    """
    query = db.query(models.JobPosition)
    if status_filter:
        try:
            norm_status = models.JobStatus(status_filter.lower().strip())
            query = query.filter(models.JobPosition.status == norm_status)
        except ValueError:
            pass
    if job_id:
        query = query.filter(models.JobPosition.id == job_id)
    if department_filter:
        query = query.filter(func.trim(func.lower(models.JobPosition.department)) == department_filter.strip().lower())

    jobs = query.all()

    # Total unique candidates in database for percentage calculation
    total_unique_candidates = db.query(func.count(distinct(models.Candidate.id))).scalar() or 0

    items: List[schemas.JobDistributionItem] = []
    mapped_candidates_set = set()

    for job in jobs:
        # Candidate count associated with this job
        cand_ids = (
            db.query(distinct(models.Candidate.id))
            .outerjoin(models.Interview, models.Interview.candidate_id == models.Candidate.id)
            .filter(
                or_(
                    models.Candidate.job_id == job.id,
                    models.Interview.job_id == job.id,
                )
            )
            .all()
        )
        cand_ids_list = [c[0] for c in cand_ids]
        mapped_candidates_set.update(cand_ids_list)
        c_count = len(cand_ids_list)

        # Interview count for this job
        iv_count = db.query(func.count(models.Interview.id)).filter(models.Interview.job_id == job.id).scalar() or 0

        pct = round((c_count / total_unique_candidates) * 100, 1) if total_unique_candidates > 0 else 0.0

        items.append(
            schemas.JobDistributionItem(
                job_id=job.id,
                title=job.title,
                department=job.department,
                status=job.status.value if hasattr(job.status, "value") else str(job.status),
                candidate_count=c_count,
                interview_count=iv_count,
                percentage=pct,
            )
        )

    # Check for unassigned / general candidates
    unassigned_count = total_unique_candidates - len(mapped_candidates_set)
    if unassigned_count > 0:
        pct_unassigned = round((unassigned_count / total_unique_candidates) * 100, 1)
        items.append(
            schemas.JobDistributionItem(
                job_id=None,
                title="General / Unassigned",
                department="General",
                status="open",
                candidate_count=unassigned_count,
                interview_count=0,
                percentage=pct_unassigned,
            )
        )

    # Sorting
    if sort_order == "lowest":
        items.sort(key=lambda x: x.candidate_count)
    elif sort_order == "title":
        items.sort(key=lambda x: x.title.lower())
    else:  # highest (default)
        items.sort(key=lambda x: x.candidate_count, reverse=True)

    return schemas.JobDistributionOut(
        jobs=items,
        total_candidates_mapped=len(mapped_candidates_set),
    )


# =============================================================================
# 6. Monthly Recruitment & Interview Trends
# =============================================================================

def get_monthly_trends(
    db: Session,
    months_count: int = 6,
    time_range: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> schemas.MonthlyTrendsOut:
    """
    Generate monthly recruitment timeline trends.
    Guarantees every calendar month in the range is returned (0 activity months are included).
    """
    now = datetime.utcnow()

    # Determine start and end date for monthly span
    if start_date and end_date:
        curr_start, curr_end, _, _, _ = parse_date_range("custom", start_date, end_date)
    elif time_range == "last_12_months" or months_count == 12:
        curr_end = now
        curr_start = (now.replace(day=1) - timedelta(days=335)).replace(day=1, hour=0, minute=0, second=0)
    else:  # Default last 6 months
        curr_end = now
        curr_start = (now.replace(day=1) - timedelta(days=150)).replace(day=1, hour=0, minute=0, second=0)

    # Generate list of month slots (year, month) from curr_start to curr_end
    slots: List[Tuple[int, int]] = []
    y, m = curr_start.year, curr_start.month
    while (y < curr_end.year) or (y == curr_end.year and m <= curr_end.month):
        slots.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    trends: List[schemas.MonthlyTrendPoint] = []
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for yr, mo in slots:
        last_day = calendar.monthrange(yr, mo)[1]
        m_start = datetime(yr, mo, 1, 0, 0, 0)
        m_end = datetime(yr, mo, last_day, 23, 59, 59, 999999)

        # Candidates registered
        cand_q = db.query(func.count(models.Candidate.id)).filter(
            models.Candidate.created_at >= m_start,
            models.Candidate.created_at <= m_end,
        )
        if job_id:
            cand_q = cand_q.filter(models.Candidate.job_id == job_id)
        if department:
            cand_q = cand_q.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            cand_q = cand_q.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
                models.Interview.interviewer_id == interviewer_id
            )
        reg_count = cand_q.scalar() or 0

        # Interviews scheduled
        iv_sched_q = db.query(func.count(models.Interview.id)).filter(
            models.Interview.scheduled_at >= m_start,
            models.Interview.scheduled_at <= m_end,
        )
        if job_id:
            iv_sched_q = iv_sched_q.filter(models.Interview.job_id == job_id)
        if department:
            iv_sched_q = iv_sched_q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            iv_sched_q = iv_sched_q.filter(models.Interview.interviewer_id == interviewer_id)
        sched_count = iv_sched_q.scalar() or 0

        # Interviews completed
        iv_comp_q = db.query(func.count(models.Interview.id)).filter(
            models.Interview.scheduled_at >= m_start,
            models.Interview.scheduled_at <= m_end,
            models.Interview.status == models.InterviewStatus.COMPLETED,
        )
        if job_id:
            iv_comp_q = iv_comp_q.filter(models.Interview.job_id == job_id)
        if department:
            iv_comp_q = iv_comp_q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            iv_comp_q = iv_comp_q.filter(models.Interview.interviewer_id == interviewer_id)
        comp_count = iv_comp_q.scalar() or 0

        # Candidates selected
        sel_q = db.query(func.count(models.Candidate.id)).filter(
            models.Candidate.status.ilike("selected"),
            or_(
                models.Candidate.selection_timestamp.between(m_start, m_end),
                models.Candidate.created_at.between(m_start, m_end),
            ),
        )
        if job_id:
            sel_q = sel_q.filter(models.Candidate.job_id == job_id)
        if department:
            sel_q = sel_q.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        if interviewer_id:
            sel_q = sel_q.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
                models.Interview.interviewer_id == interviewer_id
            )
        sel_count = sel_q.scalar() or 0

        month_key = f"{yr}-{mo:02d}"
        month_label = f"{month_names[mo]} {yr}"

        trends.append(
            schemas.MonthlyTrendPoint(
                month_key=month_key,
                month_label=month_label,
                candidates_registered=reg_count,
                interviews_scheduled=sched_count,
                interviews_completed=comp_count,
                candidates_selected=sel_count,
            )
        )

    return schemas.MonthlyTrendsOut(trends=trends)


# =============================================================================
# 7. Interviewer Performance Analytics
# =============================================================================

def get_interviewer_performance(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    user: Optional[models.User] = None,
) -> schemas.InterviewerPerformanceOut:
    """
    Calculate interviewer workload and feedback scorecard statistics.
    Restricted to HR / Admin roles. Excludes missing feedback scores from averages.
    """
    curr_start, curr_end, _, _, _ = parse_date_range(time_range, start_date, end_date)

    query = db.query(models.Interviewer)
    if interviewer_id:
        query = query.filter(models.Interviewer.id == interviewer_id)
    interviewers = query.all()

    items: List[schemas.InterviewerPerformanceItem] = []

    for itv in interviewers:
        iv_query = db.query(models.Interview).filter(
            models.Interview.interviewer_id == itv.id,
            models.Interview.scheduled_at >= curr_start,
            models.Interview.scheduled_at <= curr_end,
        )
        if job_id:
            iv_query = iv_query.filter(models.Interview.job_id == job_id)
        if department:
            iv_query = iv_query.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )

        all_ivs = iv_query.all()
        assigned_cnt = len(all_ivs)
        completed_cnt = sum(1 for iv in all_ivs if iv.status == models.InterviewStatus.COMPLETED)
        pending_cnt = sum(1 for iv in all_ivs if iv.status == models.InterviewStatus.SCHEDULED)
        cancelled_cnt = sum(
            1 for iv in all_ivs if iv.status in [models.InterviewStatus.CANCELLED, models.InterviewStatus.NO_SHOW]
        )

        # Feedback score metrics
        scores_query = (
            db.query(models.Feedback.score)
            .join(models.Interview, models.Feedback.interview_id == models.Interview.id)
            .filter(
                models.Interview.interviewer_id == itv.id,
                models.Interview.scheduled_at >= curr_start,
                models.Interview.scheduled_at <= curr_end,
                models.Feedback.score.isnot(None),
            )
        )
        if job_id:
            scores_query = scores_query.filter(models.Interview.job_id == job_id)
        if department:
            scores_query = scores_query.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
                func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
            )
        scores = [s[0] for s in scores_query.all() if s[0] is not None]
        score_count = len(scores)
        avg_score = round(sum(scores) / score_count, 2) if score_count > 0 else None

        # Feedback submission rate
        sub_rate = round((score_count / completed_cnt) * 100, 1) if completed_cnt > 0 else (100.0 if assigned_cnt == 0 else 0.0)

        items.append(
            schemas.InterviewerPerformanceItem(
                interviewer_id=itv.id,
                full_name=itv.full_name,
                title=itv.title or "Interviewer",
                email=itv.email,
                assigned_interviews=assigned_cnt,
                completed_interviews=completed_cnt,
                pending_interviews=pending_cnt,
                cancelled_interviews=cancelled_cnt,
                feedback_submission_rate=sub_rate,
                average_score=avg_score,
                score_count=score_count,
            )
        )

    # Sort by assigned interviews descending
    items.sort(key=lambda x: x.assigned_interviews, reverse=True)

    return schemas.InterviewerPerformanceOut(interviewers=items)


# =============================================================================
# 7b. Feedback Score Analysis
# =============================================================================

def get_feedback_analysis(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> schemas.FeedbackAnalysisOut:
    """Compute feedback score breakdown by score tiers and global average."""
    curr_start, curr_end, _, _, _ = parse_date_range(time_range, start_date, end_date)

    q = (
        db.query(models.Feedback.score)
        .join(models.Interview, models.Feedback.interview_id == models.Interview.id)
        .filter(
            models.Interview.scheduled_at >= curr_start,
            models.Interview.scheduled_at <= curr_end,
            models.Feedback.score.isnot(None),
        )
    )
    if job_id:
        q = q.filter(models.Interview.job_id == job_id)
    if department:
        q = q.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        q = q.filter(models.Interview.interviewer_id == interviewer_id)

    scores = [s[0] for s in q.all() if s[0] is not None]
    total = len(scores)
    avg_score = round(sum(scores) / total, 2) if total > 0 else 0.0

    r1 = sum(1 for s in scores if 1.0 <= s <= 2.0)
    r2 = sum(1 for s in scores if 2.0 < s <= 3.0)
    r3 = sum(1 for s in scores if 3.0 < s <= 4.0)
    r4 = sum(1 for s in scores if 4.0 < s <= 5.0)

    ranges = [
        schemas.ScoreRangeItem(
            score_range="1.0 - 2.0",
            label="Needs Improvement",
            count=r1,
            percentage=round((r1 / total) * 100, 1) if total > 0 else 0.0,
        ),
        schemas.ScoreRangeItem(
            score_range="2.1 - 3.0",
            label="Fair",
            count=r2,
            percentage=round((r2 / total) * 100, 1) if total > 0 else 0.0,
        ),
        schemas.ScoreRangeItem(
            score_range="3.1 - 4.0",
            label="Good",
            count=r3,
            percentage=round((r3 / total) * 100, 1) if total > 0 else 0.0,
        ),
        schemas.ScoreRangeItem(
            score_range="4.1 - 5.0",
            label="Excellent",
            count=r4,
            percentage=round((r4 / total) * 100, 1) if total > 0 else 0.0,
        ),
    ]

    return schemas.FeedbackAnalysisOut(
        average_score=avg_score,
        total_reviews=total,
        score_ranges=ranges,
        scale="1.0 - 5.0",
    )


# =============================================================================
# 8. Detailed Analytics Tables (Paginated)
# =============================================================================

def get_recent_activity(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    stage_filter: Optional[str] = None,
    user: Optional[models.User] = None,
) -> schemas.RecentActivityOut:
    """Paginated list of recent candidate recruitment activities."""
    query = db.query(models.Candidate)

    if job_id:
        query = query.filter(models.Candidate.job_id == job_id)
    if department:
        query = query.join(models.JobPosition, models.Candidate.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        query = query.join(models.Interview, models.Candidate.id == models.Interview.candidate_id).filter(
            models.Interview.interviewer_id == interviewer_id
        )
    if stage_filter:
        query = query.filter(models.Candidate.status.ilike(stage_filter.strip()))
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                models.Candidate.full_name.ilike(s),
                models.Candidate.email.ilike(s),
            )
        )

    total = query.count()
    offset = max(0, (page - 1) * page_size)
    candidates = query.order_by(models.Candidate.created_at.desc()).offset(offset).limit(page_size).all()

    items = []
    for c in candidates:
        job_title = c.job.title if c.job else "Unassigned / General"
        items.append(
            schemas.RecentActivityItem(
                candidate_id=c.id,
                candidate_name=c.full_name,
                email=c.email,
                job_title=job_title,
                stage=(c.status or "applied").capitalize(),
                registered_at=c.created_at.strftime("%b %d, %Y %H:%M") if c.created_at else "—",
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return schemas.RecentActivityOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def get_interview_summary(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    time_range: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: Optional[models.User] = None,
) -> schemas.InterviewSummaryOut:
    """Paginated list of interview records with score and details."""
    query = db.query(models.Interview)

    if time_range or (start_date and end_date):
        c_start, c_end, _, _, _ = parse_date_range(time_range, start_date, end_date)
        query = query.filter(models.Interview.scheduled_at >= c_start, models.Interview.scheduled_at <= c_end)
    if job_id:
        query = query.filter(models.Interview.job_id == job_id)
    if department:
        query = query.join(models.JobPosition, models.Interview.job_id == models.JobPosition.id).filter(
            func.trim(func.lower(models.JobPosition.department)) == department.strip().lower()
        )
    if interviewer_id:
        query = query.filter(models.Interview.interviewer_id == interviewer_id)
    if status_filter:
        query = query.filter(models.Interview.status == status_filter.lower().strip())
    if search:
        s = f"%{search.strip()}%"
        query = query.join(models.Candidate, models.Interview.candidate_id == models.Candidate.id).filter(
            or_(
                models.Candidate.full_name.ilike(s),
                models.Interview.round_name.ilike(s),
            )
        )

    total = query.count()
    offset = max(0, (page - 1) * page_size)
    interviews = query.order_by(models.Interview.scheduled_at.desc()).offset(offset).limit(page_size).all()

    items = []
    for iv in interviews:
        cand_name = iv.candidate.full_name if iv.candidate else "Unknown Candidate"
        job_title = iv.job.title if iv.job else "Unknown Job"
        itv_name = iv.interviewer.full_name if iv.interviewer else "Unknown Interviewer"
        score = iv.feedback.score if iv.feedback else None

        items.append(
            schemas.InterviewSummaryItem(
                interview_id=iv.id,
                candidate_name=cand_name,
                job_title=job_title,
                interviewer_name=itv_name,
                scheduled_at=iv.scheduled_at.strftime("%b %d, %Y %H:%M") if iv.scheduled_at else "—",
                round_name=iv.round_name or "General Round",
                status=iv.status.value if hasattr(iv.status, "value") else str(iv.status),
                feedback_score=score,
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return schemas.InterviewSummaryOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def get_job_summary(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    user: Optional[models.User] = None,
) -> schemas.JobSummaryOut:
    """Paginated summary metrics for each job position."""
    query = db.query(models.JobPosition)
    if job_id:
        query = query.filter(models.JobPosition.id == job_id)
    if department:
        query = query.filter(func.trim(func.lower(models.JobPosition.department)) == department.strip().lower())
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                models.JobPosition.title.ilike(s),
                models.JobPosition.department.ilike(s),
            )
        )

    total = query.count()
    offset = max(0, (page - 1) * page_size)
    jobs = query.order_by(models.JobPosition.created_at.desc()).offset(offset).limit(page_size).all()

    items = []
    for j in jobs:
        c_count = (
            db.query(func.count(distinct(models.Candidate.id)))
            .outerjoin(models.Interview, models.Interview.candidate_id == models.Candidate.id)
            .filter(or_(models.Candidate.job_id == j.id, models.Interview.job_id == j.id))
            .scalar()
            or 0
        )
        iv_count = db.query(func.count(models.Interview.id)).filter(models.Interview.job_id == j.id).scalar() or 0
        comp_count = (
            db.query(func.count(models.Interview.id))
            .filter(
                models.Interview.job_id == j.id,
                models.Interview.status == models.InterviewStatus.COMPLETED,
            )
            .scalar()
            or 0
        )
        sel_count = (
            db.query(func.count(models.Candidate.id))
            .filter(
                models.Candidate.job_id == j.id,
                models.Candidate.status.ilike("selected"),
            )
            .scalar()
            or 0
        )

        items.append(
            schemas.JobSummaryItem(
                job_id=j.id,
                title=j.title,
                department=j.department or "General",
                status=j.status.value if hasattr(j.status, "value") else str(j.status),
                candidate_count=c_count,
                interview_count=iv_count,
                completed_interview_count=comp_count,
                selected_count=sel_count,
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return schemas.JobSummaryOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def get_filter_options(db: Session, user: Optional[models.User] = None) -> schemas.FilterOptionsOut:
    """Retrieve distinct jobs, departments, and interviewers for populating filter controls."""
    jobs = (
        db.query(models.JobPosition.id, models.JobPosition.title, models.JobPosition.department)
        .order_by(models.JobPosition.title.asc())
        .all()
    )
    job_list = [
        {"id": j[0], "title": j[1], "department": (j[2] or "").strip()}
        for j in jobs
        if j[0] is not None and j[1]
    ]

    dept_rows = (
        db.query(distinct(func.trim(models.JobPosition.department)))
        .filter(models.JobPosition.department.isnot(None))
        .all()
    )
    departments = sorted(list({d[0].strip() for d in dept_rows if d[0] and d[0].strip()}))

    interviewers = (
        db.query(models.Interviewer.id, models.Interviewer.full_name)
        .order_by(models.Interviewer.full_name.asc())
        .all()
    )
    itv_list = [
        {"id": i[0], "name": i[1], "full_name": i[1]}
        for i in interviewers
        if i[0] is not None and i[1]
    ]

    interview_statuses = [
        {"value": "scheduled", "label": "Scheduled"},
        {"value": "completed", "label": "Completed"},
        {"value": "cancelled", "label": "Cancelled"},
        {"value": "no_show", "label": "No Show"},
    ]

    candidate_stages = [
        {"value": "applied", "label": "Applied"},
        {"value": "shortlisted", "label": "Shortlisted"},
        {"value": "interview_scheduled", "label": "Interview Scheduled"},
        {"value": "interviewed", "label": "Interviewed"},
        {"value": "selected", "label": "Selected"},
        {"value": "rejected", "label": "Rejected"},
    ]

    return schemas.FilterOptionsOut(
        jobs=job_list,
        job_positions=job_list,
        departments=departments,
        interviewers=itv_list,
        interview_statuses=interview_statuses,
        candidate_stages=candidate_stages,
    )


# =============================================================================
# 9. CSV Export Generation (Safe against Formula Injection)
# =============================================================================

def sanitize_csv_cell(value: Any) -> str:
    """Prevent CSV formula injection by prepending risky prefixes with a single quote."""
    if value is None:
        return ""
    val_str = str(value).strip()
    if val_str and val_str[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val_str}"
    return val_str


def generate_analytics_csv(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interview_status: Optional[str] = None,
    candidate_stage: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> str:
    """
    Generate complete filtered CSV report with UTF-8 encoding.
    Includes Overview KPIs, Pipeline Funnel, Job Breakdown, and Interview Logs.
    """
    kpis = get_overview_kpis(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=user,
    )
    pipeline = get_recruitment_pipeline(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=user,
    )
    jobs_dist = get_job_wise_distribution(
        db=db,
        department_filter=department,
        job_id=job_id,
        user=user,
    )

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # 1. Report Header
    writer.writerow([sanitize_csv_cell("AI-POWERED INTERVIEW MANAGEMENT AND RECRUITMENT SYSTEM")])
    writer.writerow([sanitize_csv_cell("RECRUITMENT ANALYTICS & HIRING INSIGHTS REPORT")])
    writer.writerow([sanitize_csv_cell(f"Generated At: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")])
    writer.writerow([sanitize_csv_cell(f"Filter Period: {kpis.filter_summary.get('period_label')}")])
    writer.writerow([])

    # 2. Executive KPIs Section
    writer.writerow([sanitize_csv_cell("--- RECRUITMENT KPI SUMMARY ---")])
    writer.writerow([sanitize_csv_cell("Metric"), sanitize_csv_cell("Value"), sanitize_csv_cell("Comparison vs Previous Period"), sanitize_csv_cell("Description")])
    kpi_rows = [
        ("Total Candidates", kpis.total_candidates.display_value, kpis.total_candidates.comparison_text, kpis.total_candidates.tooltip),
        ("Active Job Positions", kpis.active_jobs.display_value, kpis.active_jobs.comparison_text, kpis.active_jobs.tooltip),
        ("Total Interviews", kpis.total_interviews.display_value, kpis.total_interviews.comparison_text, kpis.total_interviews.tooltip),
        ("Interview Completion Rate", kpis.completion_rate.display_value, kpis.completion_rate.comparison_text, kpis.completion_rate.tooltip),
        ("Average Feedback Score", kpis.avg_feedback_score.display_value, kpis.avg_feedback_score.comparison_text, kpis.avg_feedback_score.tooltip),
        ("Cancelled Interviews", kpis.cancelled_interviews.display_value if kpis.cancelled_interviews else "0", kpis.cancelled_interviews.comparison_text if kpis.cancelled_interviews else "", kpis.cancelled_interviews.tooltip if kpis.cancelled_interviews else ""),
        ("Candidates Hired", kpis.candidates_hired.display_value if kpis.candidates_hired else "0", kpis.candidates_hired.comparison_text if kpis.candidates_hired else "", kpis.candidates_hired.tooltip if kpis.candidates_hired else ""),
        ("Pending Interviews", kpis.pending_interviews.display_value if kpis.pending_interviews else "0", kpis.pending_interviews.comparison_text if kpis.pending_interviews else "", kpis.pending_interviews.tooltip if kpis.pending_interviews else ""),
        ("Selection Rate", kpis.selection_rate.display_value if kpis.selection_rate else "0.0%", kpis.selection_rate.comparison_text if kpis.selection_rate else "", kpis.selection_rate.tooltip if kpis.selection_rate else ""),
    ]
    for row in kpi_rows:
        writer.writerow([sanitize_csv_cell(x) for x in row])
    writer.writerow([])

    # 3. Recruitment Pipeline Funnel
    writer.writerow([sanitize_csv_cell("--- RECRUITMENT PIPELINE FUNNEL ---")])
    writer.writerow([sanitize_csv_cell("Pipeline Stage"), sanitize_csv_cell("Current Stage Candidates"), sanitize_csv_cell("Stage Share (%)"), sanitize_csv_cell("Cumulative Milestone Reach"), sanitize_csv_cell("Funnel Conversion (%)")])
    for st in pipeline.stages:
        writer.writerow([
            sanitize_csv_cell(st.stage_label),
            sanitize_csv_cell(st.count),
            sanitize_csv_cell(f"{st.percentage}%"),
            sanitize_csv_cell(st.funnel_count),
            sanitize_csv_cell(f"{st.funnel_percentage}%"),
        ])
    writer.writerow([])

    # 4. Job-Wise Candidate Distribution
    writer.writerow([sanitize_csv_cell("--- JOB POSITION CANDIDATE DISTRIBUTION ---")])
    writer.writerow([sanitize_csv_cell("Job Title"), sanitize_csv_cell("Department"), sanitize_csv_cell("Status"), sanitize_csv_cell("Candidates Count"), sanitize_csv_cell("Interviews Count"), sanitize_csv_cell("Share of Total (%)")])
    for j in jobs_dist.jobs:
        writer.writerow([
            sanitize_csv_cell(j.title),
            sanitize_csv_cell(j.department or "General"),
            sanitize_csv_cell(j.status.capitalize()),
            sanitize_csv_cell(j.candidate_count),
            sanitize_csv_cell(j.interview_count),
            sanitize_csv_cell(f"{j.percentage}%"),
        ])
    writer.writerow([])

    # 5. Filtered Interview Records
    writer.writerow([sanitize_csv_cell("--- DETAILED INTERVIEW LOGS (FILTERED) ---")])
    writer.writerow([sanitize_csv_cell("Interview ID"), sanitize_csv_cell("Candidate"), sanitize_csv_cell("Job Position"), sanitize_csv_cell("Interviewer"), sanitize_csv_cell("Scheduled Date (UTC)"), sanitize_csv_cell("Status"), sanitize_csv_cell("Feedback Score (Out of 5)")])

    c_start, c_end, _, _, _ = parse_date_range(time_range, start_date, end_date)
    iv_query = db.query(models.Interview).filter(
        models.Interview.scheduled_at >= c_start,
        models.Interview.scheduled_at <= c_end,
    )
    if job_id:
        iv_query = iv_query.filter(models.Interview.job_id == job_id)
    if interviewer_id:
        iv_query = iv_query.filter(models.Interview.interviewer_id == interviewer_id)
    if interview_status:
        iv_query = iv_query.filter(models.Interview.status == interview_status.lower().strip())

    interviews = iv_query.order_by(models.Interview.scheduled_at.desc()).limit(500).all()
    for iv in interviews:
        writer.writerow([
            sanitize_csv_cell(iv.id),
            sanitize_csv_cell(iv.candidate.full_name if iv.candidate else "Unknown"),
            sanitize_csv_cell(iv.job.title if iv.job else "Unknown"),
            sanitize_csv_cell(iv.interviewer.full_name if iv.interviewer else "Unknown"),
            sanitize_csv_cell(iv.scheduled_at.strftime("%Y-%m-%d %H:%M") if iv.scheduled_at else ""),
            sanitize_csv_cell(iv.status.value if hasattr(iv.status, "value") else str(iv.status)),
            sanitize_csv_cell(f"{iv.feedback.score:.1f}" if iv.feedback and iv.feedback.score else "—"),
        ])

    return output.getvalue()


# =============================================================================
# 10. PDF Report Generation (ReportLab)
# =============================================================================

def generate_analytics_pdf(
    db: Session,
    time_range: Optional[str] = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    job_id: Optional[int] = None,
    department: Optional[str] = None,
    interview_status: Optional[str] = None,
    candidate_stage: Optional[str] = None,
    interviewer_id: Optional[int] = None,
    user: Optional[models.User] = None,
) -> bytes:
    """
    Generate an executive, branded Recruitment Analytics & Hiring Insights PDF Report.
    Uses ReportLab with consistent corporate typography and palette.
    """
    kpis = get_overview_kpis(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interview_status=interview_status,
        candidate_stage=candidate_stage,
        interviewer_id=interviewer_id,
        user=user,
    )
    pipeline = get_recruitment_pipeline(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=user,
    )
    iv_status = get_interview_status_distribution(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=user,
    )
    jobs_dist = get_job_wise_distribution(
        db=db,
        department_filter=department,
        job_id=job_id,
        user=user,
    )
    trends = get_monthly_trends(
        db=db,
        months_count=6,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        job_id=job_id,
        department=department,
        interviewer_id=interviewer_id,
        user=user,
    )
    itv_perf = get_interviewer_performance(
        db=db,
        time_range=time_range,
        start_date=start_date,
        end_date=end_date,
        interviewer_id=interviewer_id,
        job_id=job_id,
        department=department,
        user=user,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Colors
    c_primary = colors.HexColor("#4F46E5")      # Indigo 600
    c_primary_dark = colors.HexColor("#312E81") # Indigo 900
    c_text_dark = colors.HexColor("#1E293B")    # Slate 800
    c_text_muted = colors.HexColor("#64748B")   # Slate 500
    c_border = colors.HexColor("#E2E8F0")       # Slate 200
    c_bg_light = colors.HexColor("#F8FAFC")     # Slate 50
    c_success = colors.HexColor("#059669")      # Emerald 600

    # Typography
    title_style = ParagraphStyle(
        "PDFTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=c_primary_dark,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "PDFSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=c_text_muted,
        spaceAfter=12,
    )
    section_h2 = ParagraphStyle(
        "PDFSectionH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=c_primary,
        spaceBefore=10,
        spaceAfter=4,
    )
    cell_text = ParagraphStyle(
        "PDFCellText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=c_text_dark,
    )
    cell_header = ParagraphStyle(
        "PDFCellHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white,
    )

    elements = []

    # 1. Header Banner
    elements.append(Paragraph("AI-Powered Interview Management and Recruitment System", title_style))
    elements.append(Paragraph(
        f"Executive Recruitment Analytics Report &bull; Period: <b>{kpis.filter_summary.get('period_label')}</b> &bull; Generated: {datetime.utcnow().strftime('%b %d, %Y %H:%M UTC')}",
        subtitle_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=c_primary, spaceAfter=10))

    # 2. Executive KPI Cards Table (3 columns x 2 rows)
    elements.append(Paragraph("1. Executive Recruitment KPI Summary", section_h2))

    kpi_card_data = [
        [
            Paragraph(f"<b>Total Candidates</b><br/><font size='11' color='#1E293B'><b>{kpis.total_candidates.display_value}</b></font><br/><font size='7' color='#64748B'>{kpis.total_candidates.comparison_text}</font>", cell_text),
            Paragraph(f"<b>Active Positions</b><br/><font size='11' color='#1E293B'><b>{kpis.active_jobs.display_value}</b></font><br/><font size='7' color='#64748B'>{kpis.active_jobs.comparison_text}</font>", cell_text),
            Paragraph(f"<b>Total Interviews</b><br/><font size='11' color='#1E293B'><b>{kpis.total_interviews.display_value}</b></font><br/><font size='7' color='#64748B'>{kpis.total_interviews.comparison_text}</font>", cell_text),
            Paragraph(f"<b>Completion Rate</b><br/><font size='11' color='#059669'><b>{kpis.completion_rate.display_value}</b></font><br/><font size='7' color='#64748B'>{kpis.completion_rate.comparison_text}</font>", cell_text),
        ],
        [
            Paragraph(f"<b>Avg Feedback</b><br/><font size='11' color='#D97706'><b>{kpis.avg_feedback_score.display_value}</b></font><br/><font size='7' color='#64748B'>{kpis.avg_feedback_score.comparison_text}</font>", cell_text),
            Paragraph(f"<b>Cancelled</b><br/><font size='11' color='#DC2626'><b>{kpis.cancelled_interviews.display_value if kpis.cancelled_interviews else '0'}</b></font><br/><font size='7' color='#64748B'>{kpis.cancelled_interviews.comparison_text if kpis.cancelled_interviews else ''}</font>", cell_text),
            Paragraph(f"<b>Candidates Hired</b><br/><font size='11' color='#059669'><b>{kpis.candidates_hired.display_value if kpis.candidates_hired else '0'}</b></font><br/><font size='7' color='#64748B'>{kpis.candidates_hired.comparison_text if kpis.candidates_hired else ''}</font>", cell_text),
            Paragraph(f"<b>Pending Interviews</b><br/><font size='11' color='#4F46E5'><b>{kpis.pending_interviews.display_value if kpis.pending_interviews else '0'}</b></font><br/><font size='7' color='#64748B'>{kpis.pending_interviews.comparison_text if kpis.pending_interviews else ''}</font>", cell_text),
        ],
    ]

    t_kpis = Table(kpi_card_data, colWidths=[135, 135, 135, 135])
    t_kpis.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_bg_light),
        ("BOX", (0, 0), (-1, -1), 1, c_border),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(t_kpis)
    elements.append(Spacer(1, 10))

    # 3. Recruitment Pipeline Funnel Summary Table
    elements.append(Paragraph("2. Candidate Recruitment Pipeline Funnel", section_h2))
    p_headers = [
        Paragraph("Pipeline Stage", cell_header),
        Paragraph("Stage Candidates", cell_header),
        Paragraph("Share (%)", cell_header),
        Paragraph("Cumulative Funnel Reach", cell_header),
        Paragraph("Conversion (%)", cell_header),
    ]
    p_rows = [p_headers]
    for st in pipeline.stages:
        p_rows.append([
            Paragraph(st.stage_label, cell_text),
            Paragraph(str(st.count), cell_text),
            Paragraph(f"{st.percentage}%", cell_text),
            Paragraph(str(st.funnel_count), cell_text),
            Paragraph(f"{st.funnel_percentage}%", cell_text),
        ])

    t_pipeline = Table(p_rows, colWidths=[130, 95, 75, 130, 110])
    t_pipeline.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_bg_light]),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_pipeline)
    elements.append(Spacer(1, 10))

    # 4. Interview Status Distribution
    elements.append(Paragraph("3. Interview Status Breakdown", section_h2))
    iv_rows = [[
        Paragraph("Interview Status", cell_header),
        Paragraph("Count", cell_header),
        Paragraph("Percentage (%)", cell_header),
    ]]
    for item in iv_status.statuses:
        iv_rows.append([
            Paragraph(item.status_label, cell_text),
            Paragraph(str(item.count), cell_text),
            Paragraph(f"{item.percentage}%", cell_text),
        ])
    t_iv = Table(iv_rows, colWidths=[200, 170, 170])
    t_iv.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary_dark),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_bg_light]),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_iv)
    elements.append(Spacer(1, 10))

    # 5. Job-Wise Candidate Distribution
    elements.append(Paragraph("4. Top Job Position Candidate Distribution", section_h2))
    job_rows = [[
        Paragraph("Job Title", cell_header),
        Paragraph("Department", cell_header),
        Paragraph("Status", cell_header),
        Paragraph("Candidates", cell_header),
        Paragraph("Interviews", cell_header),
    ]]
    for j in jobs_dist.jobs[:8]:  # Top 8
        job_rows.append([
            Paragraph(j.title, cell_text),
            Paragraph(j.department or "General", cell_text),
            Paragraph(j.status.capitalize(), cell_text),
            Paragraph(str(j.candidate_count), cell_text),
            Paragraph(str(j.interview_count), cell_text),
        ])
    t_jobs = Table(job_rows, colWidths=[180, 120, 80, 80, 80])
    t_jobs.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_bg_light]),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_jobs)
    elements.append(Spacer(1, 10))

    # 6. Monthly Trends Summary Table
    elements.append(Paragraph("5. Monthly Recruitment & Interview Trends", section_h2))
    trend_rows = [[
        Paragraph("Month", cell_header),
        Paragraph("Candidates Registered", cell_header),
        Paragraph("Interviews Scheduled", cell_header),
        Paragraph("Interviews Completed", cell_header),
        Paragraph("Candidates Selected", cell_header),
    ]]
    for tp in trends.trends:
        trend_rows.append([
            Paragraph(tp.month_label, cell_text),
            Paragraph(str(tp.candidates_registered), cell_text),
            Paragraph(str(tp.interviews_scheduled), cell_text),
            Paragraph(str(tp.interviews_completed), cell_text),
            Paragraph(str(tp.candidates_selected), cell_text),
        ])
    t_trend = Table(trend_rows, colWidths=[140, 100, 100, 100, 100])
    t_trend.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary_dark),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_bg_light]),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_trend)
    elements.append(Spacer(1, 10))

    # 7. Interviewer Workload & Feedback Performance
    elements.append(Paragraph("6. Interviewer Workload & Feedback Activity", section_h2))
    itv_rows = [[
        Paragraph("Interviewer", cell_header),
        Paragraph("Title", cell_header),
        Paragraph("Assigned", cell_header),
        Paragraph("Completed", cell_header),
        Paragraph("Feedback Rate", cell_header),
        Paragraph("Avg Score (1-5)", cell_header),
    ]]
    for itv in itv_perf.interviewers[:8]:
        avg_str = f"{itv.average_score:.1f}" if itv.average_score is not None else "—"
        itv_rows.append([
            Paragraph(itv.full_name, cell_text),
            Paragraph(itv.title or "Interviewer", cell_text),
            Paragraph(str(itv.assigned_interviews), cell_text),
            Paragraph(str(itv.completed_interviews), cell_text),
            Paragraph(f"{itv.feedback_submission_rate:.1f}%", cell_text),
            Paragraph(avg_str, cell_text),
        ])
    t_itv = Table(itv_rows, colWidths=[120, 110, 75, 75, 80, 80])
    t_itv.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, c_bg_light]),
        ("GRID", (0, 0), (-1, -1), 0.5, c_border),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_itv)
    elements.append(Spacer(1, 14))

    # Footer note
    elements.append(Paragraph(
        "<i>CONFIDENTIAL &bull; For internal HR management and hiring committee use only. Generated via AI-Powered Interview Management System.</i>",
        subtitle_style,
    ))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()
