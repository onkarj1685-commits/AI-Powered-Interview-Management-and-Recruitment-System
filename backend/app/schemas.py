"""
Pydantic schemas used for request validation and response serialization.

Naming convention:
- <Entity>Base   -> shared fields
- <Entity>Create -> fields required to create the entity
- <Entity>Update -> optional fields for partial updates
- <Entity>Out    -> fields returned to the client (includes id, timestamps, nested data)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from .models import InterviewStatus, JobStatus, Recommendation


# ---------- Candidate ----------

class CandidateBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    status: Optional[str] = "applied"
    job_id: Optional[int] = None
    selection_timestamp: Optional[datetime] = None


class CandidateCreate(CandidateBase):
    pass


class CandidateUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    status: Optional[str] = None
    job_id: Optional[int] = None
    selection_timestamp: Optional[datetime] = None


class CandidateStatusUpdate(BaseModel):
    status: str = Field(..., description="Target status: applied, shortlisted, selected, rejected")
    job_id: Optional[int] = None
    notes: Optional[str] = None


class CandidateOut(CandidateBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str = "applied"
    job_id: Optional[int] = None
    selection_timestamp: Optional[datetime] = None
    created_at: datetime


# ---------- Job Position ----------

class JobPositionBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    department: Optional[str] = None
    description: Optional[str] = None
    status: JobStatus = JobStatus.OPEN


class JobPositionCreate(JobPositionBase):
    pass


class JobPositionUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    status: Optional[JobStatus] = None


class JobPositionOut(JobPositionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- Interviewer ----------

class InterviewerBase(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    title: Optional[str] = None


class InterviewerCreate(InterviewerBase):
    pass


class InterviewerUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    title: Optional[str] = None


class InterviewerOut(InterviewerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Feedback ----------

class FeedbackBase(BaseModel):
    score: float = Field(..., ge=1.0, le=5.0)
    recommendation: Recommendation
    strengths: Optional[str] = None
    concerns: Optional[str] = None
    notes: Optional[str] = None


class FeedbackCreate(FeedbackBase):
    pass


class FeedbackOut(FeedbackBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    interview_id: int
    submitted_at: datetime


# ---------- Interview ----------

class InterviewBase(BaseModel):
    candidate_id: int
    job_id: int
    interviewer_id: int
    scheduled_at: datetime
    duration_minutes: int = 45
    round_name: Optional[str] = None
    meeting_link: Optional[str] = None
    instructions: Optional[str] = None
    status: InterviewStatus = InterviewStatus.SCHEDULED


class InterviewCreate(InterviewBase):
    pass


class InterviewUpdate(BaseModel):
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    round_name: Optional[str] = None
    meeting_link: Optional[str] = None
    instructions: Optional[str] = None
    status: Optional[InterviewStatus] = None
    interviewer_id: Optional[int] = None
    reminder_sent: Optional[bool] = None


class InterviewRescheduleRequest(BaseModel):
    scheduled_at: datetime
    duration_minutes: Optional[int] = None
    round_name: Optional[str] = None
    interviewer_id: Optional[int] = None
    meeting_link: Optional[str] = None
    instructions: Optional[str] = None
    reason: Optional[str] = None


class InterviewCancelRequest(BaseModel):
    reason: Optional[str] = "Interview cancelled by HR"


class InterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    job_id: int
    interviewer_id: int
    scheduled_at: datetime
    duration_minutes: int
    round_name: Optional[str] = None
    meeting_link: Optional[str] = None
    instructions: Optional[str] = None
    reminder_sent: bool = False
    reminder_sent_at: Optional[datetime] = None
    status: InterviewStatus
    feedback: Optional[FeedbackOut] = None


class InterviewRescheduleOut(InterviewOut):
    email_sent: bool = True
    email_error: Optional[str] = None
    message: Optional[str] = None


class InterviewDetailOut(InterviewOut):
    """Interview with nested candidate/job/interviewer info for convenient display."""
    candidate: CandidateOut
    job: JobPositionOut
    interviewer: InterviewerOut


# ---------- User & Authentication ----------

class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None
    name: Optional[str] = None
    role: str = "HR/User"
    google_id: Optional[str] = None
    profile_picture: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=6, max_length=100)
    full_name: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = "admin"


class UserLogin(BaseModel):
    username_or_email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    last_login: Optional[datetime] = None


class GoogleAuthTokenRequest(BaseModel):
    credential: Optional[str] = None
    code: Optional[str] = None



class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenData(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email_or_username: str = Field(..., min_length=1)


class ForgotPasswordResponse(BaseModel):
    message: str


# ---------- Email & Notifications ----------

class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recipient: str
    notification_type: str
    subject: str
    body_html: Optional[str] = None
    candidate_id: Optional[int] = None
    interview_id: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    retry_count: int = 0
    sent_at: Optional[datetime] = None
    created_at: datetime


class SendTestEmailRequest(BaseModel):
    to_email: EmailStr
    subject: Optional[str] = "Test Email from AI Interview Management System"
    notes: Optional[str] = None


class SmtpStatusOut(BaseModel):
    configured: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    email_from: str
    frontend_url: str
    hr_notification_email: str
    message: str


# ---------- Recruitment Analytics & Hiring Insights ----------

class KPIItem(BaseModel):
    value: Union[int, float, str]
    display_value: str
    label: str
    subtext: Optional[str] = None
    previous_period_value: Optional[Union[int, float]] = None
    percentage_change: Optional[float] = None
    comparison_text: str
    trend: Optional[str] = None  # "up", "down", "neutral"
    tooltip: str


class OverviewKPIsOut(BaseModel):
    total_candidates: KPIItem
    active_jobs: KPIItem
    total_interviews: KPIItem
    completion_rate: KPIItem
    avg_feedback_score: KPIItem
    cancelled_interviews: Optional[KPIItem] = None
    candidates_hired: Optional[KPIItem] = None
    pending_interviews: Optional[KPIItem] = None
    selection_rate: Optional[KPIItem] = None
    filter_summary: Dict[str, Any]


class ScoreRangeItem(BaseModel):
    score_range: str
    label: str
    count: int
    percentage: float


class FeedbackAnalysisOut(BaseModel):
    average_score: float
    total_reviews: int
    score_ranges: List[ScoreRangeItem]
    scale: str = "1.0 - 5.0"


class PipelineStageItem(BaseModel):
    stage_key: str
    stage_label: str
    count: int
    percentage: float
    funnel_count: int
    funnel_percentage: float


class RecruitmentPipelineOut(BaseModel):
    stages: List[PipelineStageItem]
    total_candidates: int


class InterviewStatusItem(BaseModel):
    status_key: str
    status_label: str
    count: int
    percentage: float
    color: str


class InterviewStatusOut(BaseModel):
    statuses: List[InterviewStatusItem]
    total_interviews: int


class JobDistributionItem(BaseModel):
    job_id: Optional[int] = None
    title: str
    department: Optional[str] = None
    status: str
    candidate_count: int
    interview_count: int
    percentage: float


class JobDistributionOut(BaseModel):
    jobs: List[JobDistributionItem]
    total_candidates_mapped: int


class MonthlyTrendPoint(BaseModel):
    month_key: str
    month_label: str
    candidates_registered: int
    interviews_scheduled: int
    interviews_completed: int
    candidates_selected: int


class MonthlyTrendsOut(BaseModel):
    trends: List[MonthlyTrendPoint]


class InterviewerPerformanceItem(BaseModel):
    interviewer_id: int
    full_name: str
    title: Optional[str] = None
    email: str
    assigned_interviews: int
    completed_interviews: int
    pending_interviews: int
    cancelled_interviews: int
    feedback_submission_rate: float
    average_score: Optional[float] = None
    score_count: int


class InterviewerPerformanceOut(BaseModel):
    interviewers: List[InterviewerPerformanceItem]


class RecentActivityItem(BaseModel):
    candidate_id: int
    candidate_name: str
    email: str
    job_title: str
    stage: str
    registered_at: str


class RecentActivityOut(BaseModel):
    items: List[RecentActivityItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class InterviewSummaryItem(BaseModel):
    interview_id: int
    candidate_name: str
    job_title: str
    interviewer_name: str
    scheduled_at: str
    round_name: Optional[str] = None
    status: str
    feedback_score: Optional[float] = None


class InterviewSummaryOut(BaseModel):
    items: List[InterviewSummaryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class JobSummaryItem(BaseModel):
    job_id: int
    title: str
    department: Optional[str] = None
    status: str
    candidate_count: int
    interview_count: int
    completed_interview_count: int
    selected_count: int


class JobSummaryOut(BaseModel):
    items: List[JobSummaryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class FilterOptionsOut(BaseModel):
    jobs: List[Dict[str, Any]]
    job_positions: Optional[List[Dict[str, Any]]] = None
    departments: List[str]
    interviewers: List[Dict[str, Any]]
    interview_statuses: List[Dict[str, str]]
    candidate_stages: List[Dict[str, str]]


