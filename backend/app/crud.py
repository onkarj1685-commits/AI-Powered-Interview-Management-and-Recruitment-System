"""
CRUD (Create / Read / Update / Delete) helper functions.

Keeping these separate from the route handlers makes them independently
testable and reusable, and keeps the FastAPI routers thin.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from . import models, schemas



# ---------- Candidates ----------

def create_candidate(db: Session, data: schemas.CandidateCreate) -> models.Candidate:
    candidate = models.Candidate(**data.model_dump())
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    try:
        stage_entry = models.CandidateStageHistory(
            candidate_id=candidate.id,
            stage=candidate.status or "applied",
            notes="Candidate registered in system",
        )
        db.add(stage_entry)
        db.commit()
    except Exception:
        db.rollback()

    return candidate


def get_candidate(db: Session, candidate_id: int) -> Optional[models.Candidate]:
    return db.query(models.Candidate).filter(models.Candidate.id == candidate_id).first()


def get_candidate_by_email(db: Session, email: str) -> Optional[models.Candidate]:
    return db.query(models.Candidate).filter(models.Candidate.email == email).first()


def list_candidates(db: Session, skip: int = 0, limit: int = 100) -> List[models.Candidate]:
    return db.query(models.Candidate).offset(skip).limit(limit).all()


def update_candidate(
    db: Session, candidate: models.Candidate, data: schemas.CandidateUpdate
) -> models.Candidate:
    old_status = candidate.status
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(candidate, field, value)
    if candidate.status and candidate.status.lower() == "selected" and not candidate.selection_timestamp:
        candidate.selection_timestamp = datetime.utcnow()
    db.commit()
    db.refresh(candidate)

    if candidate.status and candidate.status != old_status:
        try:
            stage_entry = models.CandidateStageHistory(
                candidate_id=candidate.id,
                stage=candidate.status,
                notes="Candidate profile updated",
            )
            db.add(stage_entry)
            db.commit()
        except Exception:
            db.rollback()

    return candidate


def delete_candidate(db: Session, candidate: models.Candidate) -> None:
    db.delete(candidate)
    db.commit()


# ---------- Job Positions ----------

def create_job(db: Session, data: schemas.JobPositionCreate) -> models.JobPosition:
    job = models.JobPosition(**data.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[models.JobPosition]:
    return db.query(models.JobPosition).filter(models.JobPosition.id == job_id).first()


def list_jobs(db: Session, skip: int = 0, limit: int = 100) -> List[models.JobPosition]:
    return db.query(models.JobPosition).offset(skip).limit(limit).all()


def update_job(
    db: Session, job: models.JobPosition, data: schemas.JobPositionUpdate
) -> models.JobPosition:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job: models.JobPosition) -> None:
    db.delete(job)
    db.commit()


# ---------- Interviewers ----------

def create_interviewer(db: Session, data: schemas.InterviewerCreate) -> models.Interviewer:
    interviewer = models.Interviewer(**data.model_dump())
    db.add(interviewer)
    db.commit()
    db.refresh(interviewer)
    return interviewer


def get_interviewer(db: Session, interviewer_id: int) -> Optional[models.Interviewer]:
    return db.query(models.Interviewer).filter(models.Interviewer.id == interviewer_id).first()


def list_interviewers(db: Session, skip: int = 0, limit: int = 100) -> List[models.Interviewer]:
    return db.query(models.Interviewer).offset(skip).limit(limit).all()


def update_interviewer(
    db: Session, interviewer: models.Interviewer, data: schemas.InterviewerUpdate
) -> models.Interviewer:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(interviewer, field, value)
    db.commit()
    db.refresh(interviewer)
    return interviewer


def delete_interviewer(db: Session, interviewer: models.Interviewer) -> None:
    db.delete(interviewer)
    db.commit()


# ---------- Interviews ----------

def create_interview(db: Session, data: schemas.InterviewCreate) -> models.Interview:
    interview = models.Interview(**data.model_dump())
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return interview


def get_interview(db: Session, interview_id: int) -> Optional[models.Interview]:
    return db.query(models.Interview).filter(models.Interview.id == interview_id).first()


def list_interviews(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    candidate_id: Optional[int] = None,
    interviewer_id: Optional[int] = None,
    status: Optional[models.InterviewStatus] = None,
) -> List[models.Interview]:
    query = db.query(models.Interview)
    if candidate_id is not None:
        query = query.filter(models.Interview.candidate_id == candidate_id)
    if interviewer_id is not None:
        query = query.filter(models.Interview.interviewer_id == interviewer_id)
    if status is not None:
        query = query.filter(models.Interview.status == status)
    return query.offset(skip).limit(limit).all()


def update_interview(
    db: Session, interview: models.Interview, data: schemas.InterviewUpdate
) -> models.Interview:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(interview, field, value)
    db.commit()
    db.refresh(interview)
    return interview


def delete_interview(db: Session, interview: models.Interview) -> None:
    db.delete(interview)
    db.commit()


# ---------- Feedback ----------

def create_feedback(
    db: Session, interview: models.Interview, data: schemas.FeedbackCreate
) -> models.Feedback:
    feedback = models.Feedback(interview_id=interview.id, **data.model_dump())
    db.add(feedback)
    # Automatically mark the interview as completed once feedback is submitted.
    interview.status = models.InterviewStatus.COMPLETED
    db.commit()
    db.refresh(feedback)
    return feedback


def get_feedback_by_interview(db: Session, interview_id: int) -> Optional[models.Feedback]:
    return (
        db.query(models.Feedback)
        .filter(models.Feedback.interview_id == interview_id)
        .first()
    )


# ---------- Users & Authentication ----------

def get_user_by_id(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.email == email.lower().strip()).first()


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username.lower().strip()).first()


def get_user_by_email_or_username(db: Session, identifier: str) -> Optional[models.User]:
    ident = identifier.lower().strip()
    return (
        db.query(models.User)
        .filter((models.User.email == ident) | (models.User.username == ident))
        .first()
    )


def get_user_by_google_id(db: Session, google_id: str) -> Optional[models.User]:
    if not google_id:
        return None
    return db.query(models.User).filter(models.User.google_id == str(google_id)).first()


def generate_unique_username(db: Session, base_identifier: str) -> str:
    """Generate an available username from email or name prefix."""
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", base_identifier.lower().split("@")[0])[:20]
    if not cleaned or len(cleaned) < 3:
        cleaned = "user"
    candidate = cleaned
    counter = 1
    while get_user_by_username(db, candidate) is not None:
        candidate = f"{cleaned}_{counter}"
        counter += 1
    return candidate


def create_user(
    db: Session, data: schemas.UserCreate, hashed_password: str
) -> models.User:
    display_name = data.name or data.full_name
    user = models.User(
        email=data.email.lower().strip(),
        username=data.username.lower().strip(),
        name=display_name,
        full_name=display_name,
        hashed_password=hashed_password,
        role=data.role or "admin",
        last_login=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_or_update_google_user(
    db: Session,
    google_id: str,
    email: str,
    name: Optional[str] = None,
    profile_picture: Optional[str] = None,
) -> models.User:
    """
    Handle Google OAuth user login:
    - If user exists by google_id or email, link/update profile and update last_login.
    - If user does not exist, create a new record with default role HR/User.
    """
    norm_email = email.lower().strip()
    user = get_user_by_google_id(db, google_id)
    if not user:
        user = get_user_by_email(db, norm_email)

    now = datetime.utcnow()
    if user:
        if not user.google_id:
            user.google_id = str(google_id)
        if name:
            user.name = name
            user.full_name = name
        if profile_picture:
            user.profile_picture = profile_picture
        user.last_login = now
        db.commit()
        db.refresh(user)
        return user

    generated_username = generate_unique_username(db, norm_email)
    display_name = name or generated_username
    user = models.User(
        google_id=str(google_id),
        email=norm_email,
        username=generated_username,
        name=display_name,
        full_name=display_name,
        profile_picture=profile_picture,
        role="HR/User",
        hashed_password=None,
        created_at=now,
        last_login=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_default_user_if_empty(db: Session, hashed_password: str) -> Optional[models.User]:
    """Seed a default admin account if no users exist in the database."""
    if db.query(models.User).first() is None:
        default_user = models.User(
            email="admin@interview.com",
            username="admin",
            name="System Administrator",
            full_name="System Administrator",
            hashed_password=hashed_password,
            role="admin",
            last_login=datetime.utcnow(),
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)
        return default_user
    return None


# ---------- Notifications ----------

def update_candidate_status(
    db: Session,
    candidate: models.Candidate,
    new_status: str,
    job_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> models.Candidate:
    norm = new_status.lower().strip()
    candidate.status = norm
    if job_id is not None:
        candidate.job_id = job_id
    if norm == "selected" and not candidate.selection_timestamp:
        candidate.selection_timestamp = datetime.utcnow()
    db.commit()
    db.refresh(candidate)

    try:
        stage_entry = models.CandidateStageHistory(
            candidate_id=candidate.id,
            stage=norm,
            notes=notes or f"Pipeline status updated to {norm}",
        )
        db.add(stage_entry)
        db.commit()
    except Exception:
        db.rollback()

    return candidate


def get_notification_log(db: Session, log_id: int) -> Optional[models.NotificationLog]:
    return (
        db.query(models.NotificationLog)
        .filter(models.NotificationLog.id == log_id)
        .first()
    )


def list_notification_logs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    recipient: Optional[str] = None,
    notification_type: Optional[str] = None,
) -> List[models.NotificationLog]:
    query = db.query(models.NotificationLog)
    if status:
        query = query.filter(models.NotificationLog.status == status.lower().strip())
    if recipient:
        query = query.filter(models.NotificationLog.recipient.ilike(f"%{recipient.strip()}%"))
    if notification_type:
        query = query.filter(models.NotificationLog.notification_type == notification_type.strip())
    return (
        query.order_by(models.NotificationLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_notification_stats(db: Session) -> Dict[str, Any]:
    total = db.query(models.NotificationLog).count()
    sent = (
        db.query(models.NotificationLog)
        .filter(models.NotificationLog.status == "sent")
        .count()
    )
    failed = (
        db.query(models.NotificationLog)
        .filter(models.NotificationLog.status == "failed")
        .count()
    )
    reminders = (
        db.query(models.NotificationLog)
        .filter(models.NotificationLog.notification_type == "interview_reminder")
        .count()
    )
    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "reminders": reminders,
        "success_rate": f"{(sent / total * 100):.1f}%" if total > 0 else "100%",
    }



