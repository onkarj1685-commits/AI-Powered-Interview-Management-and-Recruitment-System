"""
SQLAlchemy ORM models for the AI-Powered Interview Management and Recruitment System.

Entities:
- Candidate: a person applying for a job
- JobPosition: an open role being hired for
- Interviewer: an employee who conducts interviews
- Interview: a scheduled interview linking a candidate, job, and interviewer
- Feedback: the scorecard/feedback left by an interviewer after an interview
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    Float,
    JSON,
    Boolean,
)
from sqlalchemy.orm import relationship

from .database import Base


class CandidateStatus(str, enum.Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    SELECTED = "selected"
    REJECTED = "rejected"


class InterviewStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class JobStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    ON_HOLD = "on_hold"


class Recommendation(str, enum.Enum):
    STRONG_YES = "strong_yes"
    YES = "yes"
    NO = "no"
    STRONG_NO = "strong_no"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationType(str, enum.Enum):
    INTERVIEW_SCHEDULED = "interview_scheduled"
    INTERVIEW_REMINDER = "interview_reminder"
    INTERVIEW_RESCHEDULED = "interview_rescheduled"
    INTERVIEW_CANCELLED = "interview_cancelled"
    STATUS_UPDATE = "status_update"
    HR_NEW_CANDIDATE = "hr_new_candidate"
    HR_EVENT = "hr_event"
    TEST_EMAIL = "test_email"


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    phone = Column(String(30), nullable=True)
    resume_url = Column(String(255), nullable=True)
    status = Column(String(50), default="applied", nullable=False)
    job_id = Column(Integer, ForeignKey("job_positions.id", ondelete="SET NULL"), nullable=True, index=True)
    selection_timestamp = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("JobPosition", back_populates="candidates")
    interviews = relationship(
        "Interview", back_populates="candidate", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "NotificationLog", back_populates="candidate", cascade="all, delete-orphan"
    )
    stage_history = relationship(
        "CandidateStageHistory", back_populates="candidate", cascade="all, delete-orphan"
    )


class CandidateStageHistory(Base):
    __tablename__ = "candidate_stage_history"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(50), nullable=False, index=True)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(Text, nullable=True)

    candidate = relationship("Candidate", back_populates="stage_history")


class JobPosition(Base):
    __tablename__ = "job_positions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(120), nullable=False)
    department = Column(String(80), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.OPEN, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    candidates = relationship("Candidate", back_populates="job")
    interviews = relationship(
        "Interview", back_populates="job", cascade="all, delete-orphan"
    )


class Interviewer(Base):
    __tablename__ = "interviewers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    title = Column(String(80), nullable=True)

    interviews = relationship("Interview", back_populates="interviewer")


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("job_positions.id"), nullable=False)
    interviewer_id = Column(Integer, ForeignKey("interviewers.id"), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=45, nullable=False)
    status = Column(Enum(InterviewStatus), default=InterviewStatus.SCHEDULED, nullable=False)
    round_name = Column(String(80), nullable=True)  # e.g. "Phone Screen", "Onsite - System Design"
    meeting_link = Column(String(500), nullable=True)
    instructions = Column(Text, nullable=True)
    reminder_sent = Column(Boolean, default=False, nullable=False)
    reminder_sent_at = Column(DateTime, nullable=True)

    candidate = relationship("Candidate", back_populates="interviews")
    job = relationship("JobPosition", back_populates="interviews")
    interviewer = relationship("Interviewer", back_populates="interviews")
    feedback = relationship(
        "Feedback", back_populates="interview", uselist=False, cascade="all, delete-orphan"
    )
    notifications = relationship(
        "NotificationLog", back_populates="interview", cascade="all, delete-orphan"
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), unique=True, nullable=False)
    score = Column(Float, nullable=False)  # e.g. 1.0 - 5.0
    recommendation = Column(Enum(Recommendation), nullable=False)
    strengths = Column(Text, nullable=True)
    concerns = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)

    interview = relationship("Interview", back_populates="feedback")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    recipient = Column(String(120), nullable=False, index=True)
    notification_type = Column(String(50), nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    body_html = Column(Text, nullable=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    interview_id = Column(Integer, ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), default="pending", nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    idempotency_key = Column(String(120), unique=True, nullable=True, index=True)
    retry_count = Column(Integer, default=0, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    candidate = relationship("Candidate", back_populates="notifications")
    interview = relationship("Interview", back_populates="notifications")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(120), unique=True, nullable=True, index=True)
    name = Column(String(120), nullable=True)
    full_name = Column(String(120), nullable=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    username = Column(String(80), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=True)
    profile_picture = Column(String(500), nullable=True)
    role = Column(String(50), default="HR/User", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_url = Column(String(500), nullable=True)
    candidate_name = Column(String(120), nullable=True)
    target_role = Column(String(120), nullable=True)
    overall_score = Column(Integer, nullable=False, default=70)
    ats_score = Column(Integer, nullable=False, default=75)
    strength = Column(String(50), nullable=False, default="Good")
    skills_found = Column(JSON, nullable=True)
    missing_skills = Column(JSON, nullable=True)
    breakdown = Column(JSON, nullable=True)
    suggestions = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    weaknesses = Column(JSON, nullable=True)
    recommendation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


