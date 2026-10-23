import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, schemas, models
from ..database import get_db
from ..services import email_service
from .auth import require_current_user

logger = logging.getLogger("interviews_router")

router = APIRouter(prefix="/interviews", tags=["Interviews"])


def _validate_references(db: Session, candidate_id: int, job_id: int, interviewer_id: int):
    if not crud.get_candidate(db, candidate_id):
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not crud.get_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job position not found")
    if not crud.get_interviewer(db, interviewer_id):
        raise HTTPException(status_code=404, detail="Interviewer not found")


@router.post("/", response_model=schemas.InterviewOut, status_code=status.HTTP_201_CREATED)
def create_interview(
    payload: schemas.InterviewCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Requirement 2.A: Schedule interview and automatically dispatch
    invitation email containing meeting link, interviewer, date/time, and instructions.
    """
    _validate_references(db, payload.candidate_id, payload.job_id, payload.interviewer_id)
    interview = crud.create_interview(db, payload)

    # Dispatch scheduled email asynchronously in background
    background_tasks.add_task(
        email_service.send_interview_scheduled_notification, interview.id
    )

    return interview


@router.get("/", response_model=list[schemas.InterviewOut])
def list_interviews(
    skip: int = 0,
    limit: int = 100,
    candidate_id: Optional[int] = None,
    interviewer_id: Optional[int] = None,
    status_filter: Optional[models.InterviewStatus] = None,
    db: Session = Depends(get_db),
):
    return crud.list_interviews(
        db,
        skip=skip,
        limit=limit,
        candidate_id=candidate_id,
        interviewer_id=interviewer_id,
        status=status_filter,
    )


@router.get("/{interview_id}", response_model=schemas.InterviewDetailOut)
def get_interview(interview_id: int, db: Session = Depends(get_db)):
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


@router.patch("/{interview_id}", response_model=schemas.InterviewOut)
def update_interview(
    interview_id: int,
    payload: schemas.InterviewUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if payload.interviewer_id and not crud.get_interviewer(db, payload.interviewer_id):
        raise HTTPException(status_code=404, detail="Interviewer not found")

    old_time = interview.scheduled_at
    old_status = interview.status

    updated = crud.update_interview(db, interview, payload)

    # Check for reschedule (time changed)
    if payload.scheduled_at and payload.scheduled_at != old_time:
        background_tasks.add_task(
            email_service.send_interview_rescheduled_notification,
            interview_id=updated.id,
            old_time=old_time,
        )

    # Check for cancellation
    if (
        payload.status == models.InterviewStatus.CANCELLED
        and old_status != models.InterviewStatus.CANCELLED
    ):
        background_tasks.add_task(
            email_service.send_interview_cancelled_notification,
            interview_id=updated.id,
            reason="Interview status marked cancelled by HR",
        )

    return updated


@router.post("/{interview_id}/reschedule", response_model=schemas.InterviewRescheduleOut)
def reschedule_interview(
    interview_id: int,
    payload: schemas.InterviewRescheduleRequest,
    current_user: models.User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Requirement 2.D & 3: Authenticate HR, validate date/time and conflicts,
    reschedule interview in PostgreSQL, and dispatch updated email notification to candidate.
    """
    # 1. Retrieve the interview by actual database ID
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview #{interview_id} not found",
        )

    # 2. Confirm the interview is not cancelled
    if interview.status == models.InterviewStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reschedule a cancelled interview. Please schedule a new interview instead.",
        )

    # 3. Validate new scheduled date and time
    if not payload.scheduled_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New interview date and time is required.",
        )

    scheduled_dt = payload.scheduled_at
    if scheduled_dt.tzinfo is not None:
        scheduled_naive = scheduled_dt.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        scheduled_naive = scheduled_dt

    # Prevent scheduling in the past (allow 2 minutes buffer for client clock skew)
    now = datetime.utcnow()
    if scheduled_naive < (now - timedelta(minutes=2)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interview date and time cannot be in the past.",
        )

    # 4. Validate interviewer if specified or changed
    target_interviewer_id = (
        payload.interviewer_id
        if payload.interviewer_id is not None
        else interview.interviewer_id
    )
    target_interviewer = crud.get_interviewer(db, target_interviewer_id)
    if not target_interviewer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected interviewer not found.",
        )

    # 5. Check for scheduling conflict with other interviews assigned to the same interviewer
    target_duration = (
        payload.duration_minutes
        if payload.duration_minutes is not None
        else (interview.duration_minutes or 45)
    )
    new_end = scheduled_naive + timedelta(minutes=target_duration)

    conflicting_interviews = (
        db.query(models.Interview)
        .filter(
            models.Interview.interviewer_id == target_interviewer_id,
            models.Interview.id != interview.id,
            models.Interview.status == models.InterviewStatus.SCHEDULED,
        )
        .all()
    )
    for conf in conflicting_interviews:
        conf_start = conf.scheduled_at
        conf_end = conf_start + timedelta(minutes=conf.duration_minutes or 45)
        # Check overlap: (StartA < EndB) and (EndA > StartB)
        if scheduled_naive < conf_end and new_end > conf_start:
            interviewer_name = target_interviewer.full_name
            time_str = conf_start.strftime("%A, %B %d, %Y at %I:%M %p")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Scheduling conflict: {interviewer_name} already has an interview scheduled at {time_str}.",
            )

    # 6. Apply updates and save to PostgreSQL using SQLAlchemy
    old_time = interview.scheduled_at
    interview.scheduled_at = scheduled_naive

    if payload.duration_minutes is not None:
        interview.duration_minutes = payload.duration_minutes
    if payload.round_name is not None:
        interview.round_name = payload.round_name
    if payload.interviewer_id is not None:
        interview.interviewer_id = payload.interviewer_id
    if payload.meeting_link is not None:
        interview.meeting_link = payload.meeting_link
    if payload.instructions is not None:
        interview.instructions = payload.instructions

    # Reset reminder state and mark status as SCHEDULED
    interview.reminder_sent = False
    interview.reminder_sent_at = None
    interview.status = models.InterviewStatus.SCHEDULED

    try:
        db.commit()
        db.refresh(interview)
    except Exception as exc:
        db.rollback()
        logger.error(f"Database error while saving rescheduled interview #{interview.id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while updating the interview.",
        )

    # 7. Dispatch updated email to candidate as a separate operation
    email_sent = True
    email_error = None

    try:
        log_entry = email_service.send_interview_rescheduled_notification(
            interview_id=interview.id,
            old_time=old_time,
            reason=payload.reason,
            db=db,
        )
        if log_entry is None or log_entry.status == "failed":
            email_sent = False
            email_error = (
                log_entry.error_message
                if (log_entry and log_entry.error_message)
                else "Email delivery could not be completed"
            )
    except Exception as exc:
        logger.error(f"Email dispatch error for interview #{interview.id}: {exc}")
        email_sent = False
        email_error = str(exc)

    return schemas.InterviewRescheduleOut(
        id=interview.id,
        candidate_id=interview.candidate_id,
        job_id=interview.job_id,
        interviewer_id=interview.interviewer_id,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        round_name=interview.round_name,
        meeting_link=interview.meeting_link,
        instructions=interview.instructions,
        reminder_sent=interview.reminder_sent,
        reminder_sent_at=interview.reminder_sent_at,
        status=interview.status,
        feedback=(
            schemas.FeedbackOut.model_validate(interview.feedback)
            if interview.feedback
            else None
        ),
        email_sent=email_sent,
        email_error=email_error,
        message=(
            "Interview rescheduled successfully! Notification email dispatched."
            if email_sent
            else "Interview rescheduled, but the email notification could not be sent."
        ),
    )


@router.post("/{interview_id}/cancel", response_model=schemas.InterviewOut)
def cancel_interview(
    interview_id: int,
    payload: schemas.InterviewCancelRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Requirement 2.D: Cancel interview and dispatch cancellation email.
    """
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.status = models.InterviewStatus.CANCELLED
    db.commit()
    db.refresh(interview)

    background_tasks.add_task(
        email_service.send_interview_cancelled_notification,
        interview_id=interview.id,
        reason=payload.reason,
    )

    return interview


@router.post("/{interview_id}/send-reminder", response_model=schemas.NotificationLogOut)
def trigger_interview_reminder(
    interview_id: int,
    db: Session = Depends(get_db),
):
    """
    Requirement 2.B: Manually trigger / resend 24-hour reminder email.
    """
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    log_entry = email_service.send_interview_reminder_notification(
        interview_id=interview.id,
        db=db,
        force=True,
    )
    if not log_entry:
        raise HTTPException(status_code=500, detail="Failed to generate or dispatch reminder email")

    if log_entry.status == "failed":
        raise HTTPException(
            status_code=502,
            detail=f"Email delivery failed: {log_entry.error_message or 'SMTP dispatch failure'}",
        )

    return log_entry


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interview(interview_id: int, db: Session = Depends(get_db)):
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    crud.delete_interview(db, interview)
    return None


# ---------- Feedback (nested under an interview) ----------

@router.post(
    "/{interview_id}/feedback",
    response_model=schemas.FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    interview_id: int, payload: schemas.FeedbackCreate, db: Session = Depends(get_db)
):
    interview = crud.get_interview(db, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if crud.get_feedback_by_interview(db, interview_id):
        raise HTTPException(
            status_code=400, detail="Feedback has already been submitted for this interview"
        )
    return crud.create_feedback(db, interview, payload)


@router.get("/{interview_id}/feedback", response_model=schemas.FeedbackOut)
def get_feedback(interview_id: int, db: Session = Depends(get_db)):
    feedback = crud.get_feedback_by_interview(db, interview_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="No feedback submitted for this interview")
    return feedback
