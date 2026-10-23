"""
FastAPI router for Email Notifications management, audit logging,
delivery retries, and SMTP diagnostics.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..services import email_service

router = APIRouter(prefix="/notifications", tags=["Email Notifications"])


@router.get("/", response_model=List[schemas.NotificationLogOut])
def list_notifications(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = Query(None, alias="status", description="sent, failed, pending"),
    recipient: Optional[str] = Query(None, description="Search by recipient email"),
    notification_type: Optional[str] = Query(None, description="Filter by event type"),
    db: Session = Depends(get_db),
):
    """
    List notification delivery history and audit trail from PostgreSQL.
    """
    return crud.list_notification_logs(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        recipient=recipient,
        notification_type=notification_type,
    )


@router.get("/stats", response_model=Dict[str, Any])
def get_notification_statistics(db: Session = Depends(get_db)):
    """
    Get notification delivery aggregate statistics.
    """
    return crud.get_notification_stats(db)


@router.get("/smtp-status", response_model=schemas.SmtpStatusOut)
def get_smtp_status():
    """
    Check Gmail SMTP configuration status safely without exposing secrets.
    """
    return email_service.get_smtp_status_summary()


@router.get("/{log_id}", response_model=schemas.NotificationLogOut)
def get_notification_detail(log_id: int, db: Session = Depends(get_db)):
    """
    Retrieve notification log details, including rendered HTML content for preview.
    """
    log_entry = crud.get_notification_log(db, log_id)
    if not log_entry:
        raise HTTPException(status_code=404, detail="Notification log not found")
    return log_entry


@router.post("/{log_id}/retry", response_model=schemas.NotificationLogOut)
def retry_notification(log_id: int, db: Session = Depends(get_db)):
    """
    Retry delivering a failed or un-sent notification email.
    """
    updated_log = email_service.retry_failed_notification(log_id, db=db)
    if not updated_log:
        raise HTTPException(status_code=404, detail="Notification log not found")
    return updated_log


@router.post("/test", response_model=schemas.NotificationLogOut, status_code=status.HTTP_201_CREATED)
def send_test_email(payload: schemas.SendTestEmailRequest, db: Session = Depends(get_db)):
    """
    Send a test email to verify Gmail SMTP configuration from dashboard.
    """
    return email_service.send_test_notification(
        to_email=payload.to_email,
        notes=payload.notes,
        db=db,
    )
