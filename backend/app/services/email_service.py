"""
Email Notification Service for AI-Powered Interview Management System.

Handles:
- Gmail SMTP connection with STARTTLS & Google App Password support
- Professional responsive HTML email templates for all recruitment events
- Idempotency & duplicate notification prevention
- Delivery tracking and audit logging in PostgreSQL
- Automated 24-hour interview reminder background scheduler with APScheduler
- Error handling, retries, and safe logging without credential exposure
"""
import email.utils
import html
import logging
import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Candidate, Interview, InterviewStatus, NotificationLog

logger = logging.getLogger("email_service")
logger.setLevel(logging.INFO)

# Global background scheduler instance
_email_scheduler: Optional[BackgroundScheduler] = None

_backend_dir = Path(__file__).resolve().parent.parent.parent
_backend_env = _backend_dir / ".env"
_root_env = _backend_dir.parent / ".env"


_env_loaded = False


def reload_env(force: bool = False) -> None:
    """Ensure environment variables from backend/.env are loaded with highest priority into os.environ."""
    global _env_loaded
    if _env_loaded and not force:
        return
    if _root_env.exists():
        load_dotenv(_root_env, override=False)
    if _backend_env.exists():
        load_dotenv(_backend_env, override=True)
    _env_loaded = True


# Initial load at module import
reload_env(force=True)


# ============================================================================
# CONFIGURATION HELPERS
# ============================================================================

def get_smtp_host() -> str:
    reload_env()
    return os.getenv("SMTP_HOST", "smtp.gmail.com").strip()


def get_smtp_port() -> int:
    reload_env()
    try:
        return int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return 587


def get_smtp_username() -> str:
    reload_env()
    return os.getenv("SMTP_USERNAME", "").strip()


def get_smtp_password() -> str:
    reload_env()
    pwd = os.getenv("SMTP_PASSWORD", "").strip()
    # Strip any spaces from Google App Passwords (e.g. 'abcd efgh ijkl mnop' -> 'abcdefghijklmnop')
    return re.sub(r"\s+", "", pwd)


def get_email_from() -> str:
    reload_env()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not sender or "@" not in sender:
        sender = get_smtp_username()
    return sender or "notifications@interviewmanagement.local"


def get_frontend_url() -> str:
    reload_env()
    url = os.getenv("FRONTEND_URL", "http://localhost:8000").strip()
    return url.rstrip("/")


def get_hr_notification_email() -> str:
    reload_env()
    hr_email = os.getenv("HR_NOTIFICATION_EMAIL", "hr@interview.com").strip()
    return hr_email or "hr@interview.com"


def is_smtp_configured() -> bool:
    """
    Check if valid, non-placeholder SMTP credentials are configured.
    """
    user = get_smtp_username()
    pwd = get_smtp_password()
    placeholders = [
        "your_sender_email@gmail.com",
        "your_google_app_password",
        "example@gmail.com",
        "user@gmail.com",
        "your_app_password",
        "",
    ]
    if not user or not pwd:
        return False
    if user.lower() in placeholders or pwd.lower() in placeholders:
        return False
    if not validate_email_address(user):
        return False
    return True


def get_smtp_status_summary() -> Dict[str, Any]:
    """
    Return non-sensitive SMTP configuration status for frontend diagnostics.
    """
    configured = is_smtp_configured()
    username = get_smtp_username()
    masked_user = (
        username[:3] + "***@" + username.split("@")[1]
        if "@" in username and len(username) > 5
        else (username if username else "Not configured")
    )

    return {
        "configured": configured,
        "smtp_host": get_smtp_host(),
        "smtp_port": get_smtp_port(),
        "smtp_username": masked_user,
        "email_from": get_email_from(),
        "frontend_url": get_frontend_url(),
        "hr_notification_email": get_hr_notification_email(),
        "message": (
            "Gmail SMTP configured and ready to dispatch live emails."
            if configured
            else "Gmail SMTP credentials are not configured or still set to placeholders in backend/.env. Please configure SMTP_USERNAME and SMTP_PASSWORD with a valid 16-character Google App Password."
        ),
    }


def validate_email_address(email_str: Optional[str]) -> bool:
    if not email_str:
        return False
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email_str.strip()))


# ============================================================================
# CORE SMTP DISPATCH
# ============================================================================

def send_raw_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Send an email via Gmail SMTP with STARTTLS.
    Never exposes passwords in logs.
    Returns (success: bool, error_message: Optional[str]).
    """
    if not validate_email_address(to_email):
        err = f"Invalid recipient email address: '{to_email}'"
        logger.warning(err)
        return False, err

    sender_email = get_email_from()
    host = get_smtp_host()
    port = get_smtp_port()
    username = get_smtp_username()
    password = get_smtp_password()

    # Plain text fallback
    if not text_content:
        # Strip simple tags for fallback
        text_content = re.sub(r"<[^>]+>", " ", html_content)
        text_content = re.sub(r"\s+", " ", text_content).strip()

    # Fast test-mode bypass if running automated test suite
    if os.getenv("TESTING") == "1" and not os.getenv("LIVE_SMTP_TEST"):
        logger.info(f"[Test Mode Mock] Email '{subject}' to <{to_email}> processed.")
        return True, None

    # If SMTP credentials are missing or placeholders
    if not is_smtp_configured():
        err_msg = (
            "Gmail SMTP credentials are not configured or still set to placeholders in backend/.env. "
            "Please configure SMTP_USERNAME and SMTP_PASSWORD with a valid 16-character Google App Password."
        )
        logger.warning(f"[SMTP Unconfigured] {err_msg} - Failed dispatch to <{to_email}>")
        return False, err_msg

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"AI-Powered Interview Management <{sender_email}>"
    msg["To"] = to_email
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="interviewmanagement.local")

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Live Gmail SMTP sending
    server = None
    try:
        logger.info(f"Connecting to SMTP server {host}:{port} for recipient <{to_email}>...")
        server = smtplib.SMTP(host, port, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(username, password)
        server.send_message(msg)
        logger.info(f"Email successfully delivered to <{to_email}> with subject '{subject}'.")
        return True, None
    except smtplib.SMTPAuthenticationError as auth_err:
        err_msg = (
            f"Gmail SMTP Authentication failed. Please verify your Google App Password "
            f"(ensure 2-Step Verification is active and you generated a 16-character App Password). "
            f"({auth_err.smtp_code})"
        )
        logger.error(err_msg)
        return False, err_msg
    except smtplib.SMTPConnectError as conn_err:
        err_msg = f"Failed to connect to SMTP host {host}:{port}. ({conn_err})"
        logger.error(err_msg)
        return False, err_msg
    except Exception as exc:
        err_msg = f"SMTP dispatch error: {type(exc).__name__} - {str(exc)}"
        logger.error(f"Failed to send email to <{to_email}>: {err_msg}")
        return False, err_msg
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


# ============================================================================
# AUDIT & IDEMPOTENCY TRACKING
# ============================================================================

def record_and_dispatch_notification(
    db: Session,
    recipient: str,
    notification_type: str,
    subject: str,
    body_html: str,
    candidate_id: Optional[int] = None,
    interview_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    body_text: Optional[str] = None,
    force: bool = False,
) -> NotificationLog:
    """
    Log notification in PostgreSQL, prevent duplicates via idempotency_key,
    and dispatch the email.
    """
    # 1. Check idempotency: If already sent with this key and not force, return existing record
    log_entry = None
    if idempotency_key:
        existing = (
            db.query(NotificationLog)
            .filter(NotificationLog.idempotency_key == idempotency_key)
            .first()
        )
        if existing and existing.status == "sent" and not force:
            logger.info(f"Idempotency hit: Notification '{idempotency_key}' already sent to {recipient}. Skipping.")
            return existing
        elif existing:
            log_entry = existing
            log_entry.recipient = recipient
            log_entry.notification_type = notification_type
            log_entry.subject = subject
            log_entry.body_html = body_html
            log_entry.status = "pending"
            log_entry.retry_count = (log_entry.retry_count or 0) + 1
            try:
                db.commit()
            except Exception as commit_err:
                db.rollback()
                logger.warning(f"Error resetting existing log entry status: {commit_err}")

    # 2. Create pending log if no existing record
    if log_entry is None:
        log_entry = NotificationLog(
            recipient=recipient,
            notification_type=notification_type,
            subject=subject,
            body_html=body_html,
            candidate_id=candidate_id,
            interview_id=interview_id,
            status="pending",
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(log_entry)
        try:
            db.commit()
            db.refresh(log_entry)
        except Exception as commit_err:
            db.rollback()
            logger.warning(f"Failed to commit initial notification log: {commit_err}")

    # 3. Dispatch email
    try:
        success, error_msg = send_raw_email(
            to_email=recipient,
            subject=subject,
            html_content=body_html,
            text_content=body_text,
        )
    except Exception as exc:
        success = False
        error_msg = f"Email dispatch exception: {exc}"

    # 4. Update delivery status
    if log_entry:
        if success:
            log_entry.status = "sent"
            log_entry.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            log_entry.error_message = None
        else:
            log_entry.status = "failed"
            log_entry.error_message = error_msg

        try:
            db.commit()
            db.refresh(log_entry)
        except Exception as update_err:
            db.rollback()
            logger.error(f"Failed to update notification log final status: {update_err}")

    return log_entry


# ============================================================================
# HTML EMAIL TEMPLATES
# ============================================================================

def _base_email_wrapper(title: str, badge_text: str, badge_color: str, content_html: str) -> str:
    """
    Clean, professional, mobile-responsive HTML email layout.
    White background, dark navy headings (#0F172A), and subtle purple accent (#6366F1).
    Displays project name at the top and HR contact in footer.
    """
    frontend_url = get_frontend_url()
    hr_email = html.escape(get_hr_notification_email())
    current_year = datetime.now().year

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; -webkit-font-smoothing: antialiased; color: #1E293B;">
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F8FAFC; padding: 36px 12px;">
    <tr>
      <td align="center">
        <!-- Main Container Card -->
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #FFFFFF; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05); border: 1px solid #E2E8F0;">
          
          <!-- Header Bar with dark navy background and subtle purple accent -->
          <tr>
            <td style="background: #0F172A; border-top: 4px solid #6366F1; padding: 24px 32px; text-align: left;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td>
                    <div style="display: inline-block; font-size: 16px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.01em;">
                      <span style="display: inline-block; background: #6366F1; color: #FFFFFF; width: 24px; height: 24px; line-height: 24px; text-align: center; border-radius: 6px; font-size: 13px; margin-right: 8px; vertical-align: middle;">✦</span>
                      AI-Powered Interview Management and Recruitment System
                    </div>
                  </td>
                  <td align="right">
                    <span style="display: inline-block; background-color: {badge_color}; color: #FFFFFF; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 5px 12px; border-radius: 20px;">
                      {html.escape(badge_text)}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content Body -->
          <tr>
            <td style="padding: 32px 32px 28px; background-color: #FFFFFF;">
              {content_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F8FAFC; padding: 20px 32px; text-align: center; border-top: 1px solid #E2E8F0; color: #64748B; font-size: 12px; line-height: 1.6;">
              <p style="margin: 0 0 6px 0; font-weight: 700; color: #334155;">
                AI-Powered Interview Management and Recruitment System
              </p>
              <p style="margin: 0 0 8px 0; color: #64748B;">
                If you have questions, contact the HR team at <a href="mailto:{hr_email}" style="color: #6366F1; text-decoration: none; font-weight: 600;">{hr_email}</a>
              </p>
              <p style="margin: 0; font-size: 11px; color: #94A3B8;">
                &copy; {current_year} All rights reserved. &bull; <a href="{frontend_url}" style="color: #6366F1; text-decoration: none; font-weight: 600;">Visit Recruitment Portal</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def format_interview_date(dt: Any) -> str:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if isinstance(dt, datetime):
        day = dt.strftime("%d").lstrip("0")
        month_year = dt.strftime("%B %Y")
        return f"{day} {month_year}"
    return str(dt)


def format_interview_time(dt: Any) -> str:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if isinstance(dt, datetime):
        return dt.strftime("%I:%M %p").lstrip("0")
    return str(dt)


def _format_location(meeting_link: Optional[str]) -> Tuple[str, str]:
    """Returns (plain_text_location, html_location) avoiding None/null values."""
    if not meeting_link or not meeting_link.strip():
        text_loc = "Virtual / Google Meet (Link provided by HR)"
        html_loc = "Virtual / Google Meet (Link provided by HR)"
        return text_loc, html_loc
    clean_link = meeting_link.strip()
    if clean_link.startswith("http://") or clean_link.startswith("https://"):
        return clean_link, f'<a href="{html.escape(clean_link)}" target="_blank" style="color: #6366F1; text-decoration: underline; font-weight: 600; word-break: break-all;">{html.escape(clean_link)}</a>'
    return clean_link, html.escape(clean_link)


def build_interview_scheduled_email(
    candidate_name: str,
    job_title: str,
    round_name: str,
    scheduled_at: Any,
    duration_minutes: int,
    interviewer_name: str,
    interviewer_title: Optional[str] = None,
    meeting_link: Optional[str] = None,
    instructions: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Template A: Interview Scheduled Email
    Subject: Interview Scheduled – {job_title} | AI Interview Management
    """
    cand_name = candidate_name.strip() if candidate_name and candidate_name.strip() else "Candidate"
    job = job_title.strip() if job_title and job_title.strip() else "Position"
    round_str = round_name.strip() if round_name and round_name.strip() else "Interview Round"
    interviewer = interviewer_name.strip() if interviewer_name and interviewer_name.strip() else "HR Team"
    date_str = format_interview_date(scheduled_at)
    time_str = format_interview_time(scheduled_at)
    loc_text, loc_html = _format_location(meeting_link)

    text_content = (
        f"Dear {cand_name},\n\n"
        "Congratulations! Your interview has been scheduled. Please find the details below.\n\n"
        "Interview Details\n"
        f"- Candidate Name: {cand_name}\n"
        f"- Job Position: {job}\n"
        f"- Interview Round: {round_str}\n"
        f"- Interview Date: {date_str}\n"
        f"- Interview Time: {time_str}\n"
        f"- Interviewer: {interviewer}\n"
        f"- Interview Mode/Location: {loc_text}\n\n"
        "Please be available at the scheduled time. If you have any questions or need to reschedule, please contact the HR team.\n\n"
        "We wish you the very best for your interview!\n\n"
        "Best regards,\n"
        "HR Team\n"
        "AI-Powered Interview Management and Recruitment System"
    )

    action_btn = ""
    if meeting_link and (meeting_link.strip().startswith("http://") or meeting_link.strip().startswith("https://")):
        action_btn = f"""
        <div style="text-align: center; margin: 24px 0 20px;">
          <a href="{html.escape(meeting_link.strip())}" target="_blank" style="display: inline-block; background: #6366F1; color: #FFFFFF; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 8px; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);">
            Join Interview Meeting &rarr;
          </a>
        </div>
        """

    instructions_block = ""
    if instructions and instructions.strip():
        instructions_block = f"""
        <div style="background-color: #F8FAFC; border-left: 4px solid #6366F1; padding: 12px 16px; border-radius: 6px; margin: 20px 0;">
          <div style="font-weight: 700; color: #0F172A; font-size: 13px; margin-bottom: 4px;">Special Instructions:</div>
          <div style="color: #475569; font-size: 13px; line-height: 1.5;">{html.escape(instructions.strip())}</div>
        </div>
        """

    content_html = f"""
    <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Dear <strong>{html.escape(cand_name)}</strong>,
    </p>
    <p style="margin: 0 0 20px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Congratulations! Your interview has been scheduled. Please find the details below.
    </p>

    <!-- Interview Details Card -->
    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
      <div style="font-size: 14px; font-weight: 800; color: #0F172A; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #F1F5F9; padding-bottom: 8px;">
        Interview Details
      </div>
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding: 8px 0; color: #64748B; font-weight: 600; font-size: 13px; width: 170px;">- Candidate Name:</td>
          <td style="padding: 8px 0; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(cand_name)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Job Position:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(job)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Round:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(round_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Date:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(date_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Time:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(time_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interviewer:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(interviewer)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Mode/Location:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #0F172A;">{loc_html}</td>
        </tr>
      </table>
    </div>

    {action_btn}
    {instructions_block}

    <p style="margin: 20px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      Please be available at the scheduled time. If you have any questions or need to reschedule, please contact the HR team.
    </p>
    <p style="margin: 14px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      We wish you the very best for your interview!
    </p>
    <p style="margin: 20px 0 0 0; font-size: 14px; color: #334155; line-height: 1.6;">
      Best regards,<br>
      <strong>HR Team</strong><br>
      <span style="color: #64748B; font-size: 13px;">AI-Powered Interview Management and Recruitment System</span>
    </p>
    """

    full_html = _base_email_wrapper(
        title=f"Interview Scheduled – {job} | AI Interview Management",
        badge_text="Scheduled",
        badge_color="#6366F1",
        content_html=content_html,
    )
    return full_html, text_content


def build_interview_reminder_email(
    candidate_name: str,
    job_title: str,
    round_name: str,
    scheduled_at: Any,
    duration_minutes: int,
    interviewer_name: str,
    meeting_link: Optional[str] = None,
    instructions: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Template B: Interview Reminder Email
    Subject: Reminder: Your Interview is Coming Up – {interview_date}
    """
    cand_name = candidate_name.strip() if candidate_name and candidate_name.strip() else "Candidate"
    job = job_title.strip() if job_title and job_title.strip() else "Position"
    round_str = round_name.strip() if round_name and round_name.strip() else "Interview Round"
    interviewer = interviewer_name.strip() if interviewer_name and interviewer_name.strip() else "HR Team"
    date_str = format_interview_date(scheduled_at)
    time_str = format_interview_time(scheduled_at)
    loc_text, loc_html = _format_location(meeting_link)

    text_content = (
        f"Dear {cand_name},\n\n"
        "This is a friendly reminder about your upcoming interview.\n\n"
        "Interview Details\n"
        f"- Job Position: {job}\n"
        f"- Interview Round: {round_str}\n"
        f"- Date: {date_str}\n"
        f"- Time: {time_str}\n"
        f"- Interviewer: {interviewer}\n"
        f"- Interview Mode/Location: {loc_text}\n\n"
        "Please be ready at the scheduled time.\n\n"
        "Best of luck!\n\n"
        "Best regards,\n"
        "HR Team\n"
        "AI-Powered Interview Management and Recruitment System"
    )

    action_btn = ""
    if meeting_link and (meeting_link.strip().startswith("http://") or meeting_link.strip().startswith("https://")):
        action_btn = f"""
        <div style="text-align: center; margin: 24px 0 20px;">
          <a href="{html.escape(meeting_link.strip())}" target="_blank" style="display: inline-block; background: #6366F1; color: #FFFFFF; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 8px; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);">
            Join Interview &rarr;
          </a>
        </div>
        """

    content_html = f"""
    <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Dear <strong>{html.escape(cand_name)}</strong>,
    </p>
    <p style="margin: 0 0 20px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      This is a friendly reminder about your upcoming interview.
    </p>

    <!-- Interview Details Card -->
    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
      <div style="font-size: 14px; font-weight: 800; color: #0F172A; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #F1F5F9; padding-bottom: 8px;">
        Interview Details
      </div>
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding: 8px 0; color: #64748B; font-weight: 600; font-size: 13px; width: 170px;">- Job Position:</td>
          <td style="padding: 8px 0; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(job)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Round:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(round_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Date:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(date_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Time:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(time_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interviewer:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(interviewer)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Mode/Location:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #0F172A;">{loc_html}</td>
        </tr>
      </table>
    </div>

    {action_btn}

    <p style="margin: 20px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      Please be ready at the scheduled time.
    </p>
    <p style="margin: 14px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      Best of luck!
    </p>
    <p style="margin: 20px 0 0 0; font-size: 14px; color: #334155; line-height: 1.6;">
      Best regards,<br>
      <strong>HR Team</strong><br>
      <span style="color: #64748B; font-size: 13px;">AI-Powered Interview Management and Recruitment System</span>
    </p>
    """

    full_html = _base_email_wrapper(
        title=f"Reminder: Your Interview is Coming Up – {date_str}",
        badge_text="Reminder",
        badge_color="#6366F1",
        content_html=content_html,
    )
    return full_html, text_content


def build_interview_rescheduled_email(
    candidate_name: str,
    job_title: Optional[str],
    round_name: str,
    new_date_str: str,
    new_time_str: str,
    interviewer_name: Optional[str],
    meeting_link: Optional[str] = None,
    reason: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Template C: Interview Rescheduled Email
    Subject: Interview Rescheduled – Updated Interview Details
    """
    cand_name = candidate_name.strip() if candidate_name and candidate_name.strip() else "Candidate"
    job = job_title.strip() if job_title and job_title.strip() else "Not specified"
    round_str = round_name.strip() if round_name and round_name.strip() else "Interview Round"
    interviewer = interviewer_name.strip() if interviewer_name and interviewer_name.strip() else "HR Team"
    loc_text, loc_html = _format_location(meeting_link)

    # Plain text format following Section 5 exactly
    reason_plain = f"\n\nReason for Rescheduling: {reason.strip()}" if reason and reason.strip() else ""

    text_content = (
        f"Dear {cand_name},\n\n"
        "Your interview has been rescheduled. Your interview schedule has been updated. Please review the updated details below.\n\n"
        "Updated Interview Details\n"
        f"- Candidate Name: {cand_name}\n"
        f"- Job Position: {job}\n"
        f"- Interview Round: {round_str}\n"
        f"- Interview Date: {new_date_str}\n"
        f"- Interview Time: {new_time_str}\n"
        f"- New Date: {new_date_str}\n"
        f"- New Time: {new_time_str}\n"
        f"- Interviewer: {interviewer}\n"
        f"- Interview Mode/Location: {loc_text}"
        f"{reason_plain}\n\n"
        "Please follow the updated schedule. If you have any questions, please contact the HR team.\n\n"
        "Best regards,\n"
        "HR Team\n"
        "AI-Powered Interview Management and Recruitment System"
    )

    reason_html = ""
    if reason and reason.strip():
        reason_html = f"""
        <div style="background-color: #F5F3FF; border-left: 4px solid #6366F1; padding: 14px 18px; border-radius: 6px; margin: 20px 0; font-size: 13px; color: #4338CA;">
          <strong style="color: #312E81;">Reason for Rescheduling:</strong> {html.escape(reason.strip())}
        </div>
        """

    action_btn = ""
    if meeting_link and (meeting_link.strip().startswith("http://") or meeting_link.strip().startswith("https://")):
        action_btn = f"""
        <div style="text-align: center; margin: 24px 0 20px;">
          <a href="{html.escape(meeting_link.strip())}" target="_blank" style="display: inline-block; background: #6366F1; color: #FFFFFF; font-weight: 700; font-size: 14px; text-decoration: none; padding: 12px 28px; border-radius: 8px; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);">
            Join Interview Meeting &rarr;
          </a>
        </div>
        """

    content_html = f"""
    <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Dear <strong>{html.escape(cand_name)}</strong>,
    </p>
    <p style="margin: 0 0 20px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Your interview has been rescheduled. Please review the updated details below.
    </p>

    <!-- Updated Interview Details Card -->
    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
      <div style="font-size: 14px; font-weight: 800; color: #0F172A; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #F1F5F9; padding-bottom: 8px;">
        Updated Interview Details
      </div>
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding: 8px 0; color: #64748B; font-weight: 600; font-size: 13px; width: 180px;">- Candidate Name:</td>
          <td style="padding: 8px 0; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(cand_name)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Job Position:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(job)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Round:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(round_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Date:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #6366F1;">{html.escape(new_date_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Time:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #6366F1;">{html.escape(new_time_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interviewer:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(interviewer)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Mode/Location:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #0F172A;">{loc_html}</td>
        </tr>
      </table>
    </div>

    {reason_html}
    {action_btn}

    <p style="margin: 20px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      Please follow the updated schedule. If you have any questions, please contact the HR team.
    </p>
    <p style="margin: 20px 0 0 0; font-size: 14px; color: #334155; line-height: 1.6;">
      Best regards,<br>
      <strong>HR Team</strong><br>
      <span style="color: #64748B; font-size: 13px;">AI-Powered Interview Management and Recruitment System</span>
    </p>
    """

    full_html = _base_email_wrapper(
        title="Interview Rescheduled – Updated Interview Details",
        badge_text="Rescheduled",
        badge_color="#6366F1",
        content_html=content_html,
    )
    return full_html, text_content


def build_interview_cancelled_email(
    candidate_name: str,
    job_title: str,
    round_name: str,
    previous_date_str: str,
    previous_time_str: str,
    reason: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Template D: Interview Cancellation Email
    Subject: Interview Cancellation – {job_title}
    """
    cand_name = candidate_name.strip() if candidate_name and candidate_name.strip() else "Candidate"
    job = job_title.strip() if job_title and job_title.strip() else "Position"
    round_str = round_name.strip() if round_name and round_name.strip() else "Interview Round"

    text_content = (
        f"Dear {cand_name},\n\n"
        "We would like to inform you that your scheduled interview has been cancelled.\n\n"
        f"- Job Position: {job}\n"
        f"- Interview Round: {round_str}\n"
        f"- Previous Date: {previous_date_str}\n"
        f"- Previous Time: {previous_time_str}\n\n"
        "Please contact the HR team if you need further information.\n\n"
        "Best regards,\n"
        "HR Team\n"
        "AI-Powered Interview Management and Recruitment System"
    )

    reason_block = ""
    if reason and reason.strip():
        reason_block = f"""
        <div style="background-color: #FEE2E2; border-left: 4px solid #EF4444; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; font-size: 13px; color: #991B1B;">
          <strong>Reason:</strong> {html.escape(reason.strip())}
        </div>
        """

    content_html = f"""
    <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      Dear <strong>{html.escape(cand_name)}</strong>,
    </p>
    <p style="margin: 0 0 20px 0; font-size: 15px; color: #334155; line-height: 1.6;">
      We would like to inform you that your scheduled interview has been cancelled.
    </p>

    {reason_block}

    <!-- Cancellation Details Card -->
    <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding: 8px 0; color: #64748B; font-weight: 600; font-size: 13px; width: 160px;">- Job Position:</td>
          <td style="padding: 8px 0; font-size: 14px; font-weight: 700; color: #0F172A;">{html.escape(job)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Interview Round:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 600; color: #334155;">{html.escape(round_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Previous Date:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #EF4444;">{html.escape(previous_date_str)}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; color: #64748B; font-weight: 600; font-size: 13px;">- Previous Time:</td>
          <td style="padding: 8px 0; border-top: 1px solid #F1F5F9; font-size: 14px; font-weight: 700; color: #EF4444;">{html.escape(previous_time_str)}</td>
        </tr>
      </table>
    </div>

    <p style="margin: 20px 0 0 0; font-size: 14px; color: #475569; line-height: 1.6;">
      Please contact the HR team if you need further information.
    </p>
    <p style="margin: 20px 0 0 0; font-size: 14px; color: #334155; line-height: 1.6;">
      Best regards,<br>
      <strong>HR Team</strong><br>
      <span style="color: #64748B; font-size: 13px;">AI-Powered Interview Management and Recruitment System</span>
    </p>
    """

    full_html = _base_email_wrapper(
        title=f"Interview Cancellation – {job}",
        badge_text="Cancelled",
        badge_color="#EF4444",
        content_html=content_html,
    )
    return full_html, text_content


def build_status_update_email(
    candidate_name: str,
    job_title: str,
    new_status: str,
    notes: Optional[str] = None,
) -> str:
    """Template C: Application Status Update (Shortlisted, Selected, Rejected)"""
    status_lower = new_status.lower().strip()

    if status_lower == "shortlisted":
        badge_text = "Shortlisted"
        badge_color = "#2563EB"
        title = "Great News: You've Been Shortlisted! 🌟"
        body_text = f"""
        <p style="font-size: 15px; color: #1E293B; line-height: 1.6; margin-bottom: 16px;">
          Congratulations! After reviewing your credentials and application for <strong>{job_title}</strong>, our hiring panel was very impressed by your profile.
        </p>
        <div style="background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; padding: 18px 22px; margin-bottom: 20px;">
          <div style="font-weight: 700; color: #1D4ED8; font-size: 14px; margin-bottom: 6px;">🚀 Next Steps:</div>
          <div style="font-size: 13px; color: #1E40AF; line-height: 1.6;">
            Our talent acquisition coordinator is preparing the interview schedule and will reach out shortly with available calendar slots for your first technical round.
          </div>
        </div>
        """
    elif status_lower == "selected":
        badge_text = "Selected"
        badge_color = "#059669"
        title = "Congratulations! You Have Been Selected! 🏆"
        body_text = f"""
        <p style="font-size: 15px; color: #1E293B; line-height: 1.6; margin-bottom: 16px;">
          We are thrilled to inform you that you have successfully completed all evaluation stages and have been <strong>selected</strong> for the <strong>{job_title}</strong> position!
        </p>
        <div style="background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px; padding: 18px 22px; margin-bottom: 20px;">
          <div style="font-weight: 700; color: #047857; font-size: 14px; margin-bottom: 6px;">🎉 Welcome to the Team!</div>
          <div style="font-size: 13px; color: #065F46; line-height: 1.6;">
            Our HR team is currently finalizing your formal offer letter and compensation package. Expect a follow-up email from our human resources team with complete onboarding guidelines.
          </div>
        </div>
        """
    else:  # rejected
        badge_text = "Application Update"
        badge_color = "#64748B"
        title = "Update regarding your application"
        body_text = f"""
        <p style="font-size: 14px; color: #334155; line-height: 1.6; margin-bottom: 16px;">
          Thank you for taking the time to consider our company and for interviewing for the <strong>{job_title}</strong> role.
        </p>
        <p style="font-size: 14px; color: #475569; line-height: 1.6; margin-bottom: 16px;">
          After thoughtful evaluation among an exceptionally talented pool of applicants, we have decided to move forward with other candidates whose experience more closely aligns with our immediate technical requirements.
        </p>
        <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px 20px; margin-bottom: 20px; font-size: 13px; color: #475569; line-height: 1.6;">
          We deeply appreciate the effort you invested throughout this process. We will maintain your profile in our talent pool for future openings that match your background.
        </div>
        """

    notes_html = (
        f'<div style="background:#F1F5F9; padding:12px 16px; border-radius:6px; font-size:13px; color:#475569; margin-bottom:20px;"><strong>Note from HR:</strong> {notes}</div>'
        if notes
        else ""
    )

    content = f"""
    <h2 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 800; color: #0F172A; letter-spacing: -0.02em;">
      {title}
    </h2>
    <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155;">
      Dear <strong>{candidate_name}</strong>,
    </p>
    {body_text}
    {notes_html}
    <p style="margin: 20px 0 0 0; font-size: 14px; color: #334155; line-height: 1.6;">
      Warm regards,<br>
      <strong>Talent Acquisition & HR Team</strong>
    </p>
    """
    return _base_email_wrapper(
        title=f"Application Update: {job_title}",
        badge_text=badge_text,
        badge_color=badge_color,
        content_html=content,
    )


def build_hr_notification_email(
    event_title: str,
    event_type: str,
    details: Dict[str, str],
    action_url: Optional[str] = None,
) -> str:
    """Template E: HR Recruitment Event Notification"""
    rows_html = "".join(
        f"""
        <tr>
          <td style="padding: 8px 0; border-top: 1px solid #E2E8F0; color: #64748B; font-weight: 600; font-size: 13px; width: 140px;">{k}</td>
          <td style="padding: 8px 0; border-top: 1px solid #E2E8F0; font-size: 13px; color: #0F172A; font-weight: 600;">{v}</td>
        </tr>
        """
        for k, v in details.items()
    )

    cta_btn = ""
    if action_url:
        cta_btn = f"""
        <div style="text-align: center; margin: 26px 0 16px;">
          <a href="{action_url}" target="_blank" style="display: inline-block; background: #0F172A; color: #FFFFFF; font-weight: 700; font-size: 13px; text-decoration: none; padding: 11px 26px; border-radius: 6px;">
            Open in Roster Dashboard &rarr;
          </a>
        </div>
        """

    content = f"""
    <h2 style="margin: 0 0 8px 0; font-size: 20px; font-weight: 800; color: #0F172A;">
      📢 {event_title}
    </h2>
    <p style="margin: 0 0 18px 0; font-size: 14px; color: #475569;">
      A key recruitment action has occurred in the AI Interview Management platform:
    </p>

    <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
        {rows_html}
      </table>
    </div>

    {cta_btn}
    """
    return _base_email_wrapper(
        title=event_title,
        badge_text=event_type,
        badge_color="#6366F1",
        content_html=content,
    )


def build_test_email(recipient_email: str, notes: Optional[str] = None) -> str:
    """Template: Gmail SMTP Test Email"""
    smtp_info = get_smtp_status_summary()
    content = f"""
    <h2 style="margin: 0 0 10px 0; font-size: 22px; font-weight: 800; color: #059669;">
      ✅ Gmail SMTP Connected Successfully!
    </h2>
    <p style="margin: 0 0 16px 0; font-size: 14px; color: #334155; line-height: 1.6;">
      This test message confirms that your Gmail SMTP configuration in the AI-Powered Interview Management System is functioning properly.
    </p>

    <div style="background-color: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 10px; padding: 18px 22px; margin-bottom: 20px; font-size: 13px;">
      <div style="font-weight: 700; color: #065F46; margin-bottom: 8px;">Diagnostics:</div>
      <ul style="margin: 0; padding-left: 20px; color: #047857; line-height: 1.7;">
        <li><strong>SMTP Host:</strong> {smtp_info['smtp_host']}:{smtp_info['smtp_port']} (STARTTLS)</li>
        <li><strong>Sender Account:</strong> {smtp_info['email_from']}</li>
        <li><strong>Configured Mode:</strong> {'Live Gmail SMTP' if smtp_info['configured'] else 'Simulated Testing'}</li>
        <li><strong>Timestamp:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</li>
      </ul>
    </div>

    {f'<p style="font-size: 13px; color: #475569;"><strong>Notes:</strong> {notes}</p>' if notes else ''}

    <p style="font-size: 13px; color: #64748B; margin-top: 20px;">
      Automated email services for interview invitations, 24-hour reminders, and candidate status notifications are active.
    </p>
    """
    return _base_email_wrapper(
        title="SMTP Test Verification",
        badge_text="SMTP Test",
        badge_color="#059669",
        content_html=content,
    )


# ============================================================================
# HIGH LEVEL BUSINESS NOTIFICATION WORKFLOWS
# ============================================================================

def send_interview_scheduled_notification(interview_id: int, db: Optional[Session] = None) -> Optional[NotificationLog]:
    """
    Requirement 2.A: Triggered when HR schedules an interview.
    Sends full details to candidate and alerts HR.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview or not interview.candidate:
            logger.warning(f"Interview #{interview_id} or candidate not found for email notification.")
            return None

        cand = interview.candidate
        job = interview.job
        interviewer = interview.interviewer

        candidate_name = cand.full_name
        job_title = job.title if job else "Position"
        round_name = interview.round_name or "Interview Round"
        scheduled_at_str = interview.scheduled_at.strftime("%A, %B %d, %Y at %I:%M %p")
        duration = interview.duration_minutes
        interviewer_name = interviewer.full_name if interviewer else "Hiring Manager"
        interviewer_title = interviewer.title if interviewer else None
        meeting_link = interview.meeting_link or f"{get_frontend_url()}#/interview/{interview.id}"
        instructions = interview.instructions

        # Build candidate email
        subject = f"Interview Scheduled – {job_title} | AI Interview Management"
        body_html, body_text = build_interview_scheduled_email(
            candidate_name=candidate_name,
            job_title=job_title,
            round_name=round_name,
            scheduled_at=interview.scheduled_at,
            duration_minutes=duration,
            interviewer_name=interviewer_name,
            interviewer_title=interviewer_title,
            meeting_link=interview.meeting_link,
            instructions=instructions,
        )

        idempotency_key = f"interview_scheduled_{interview.id}"
        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=cand.email,
            notification_type="interview_scheduled",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            candidate_id=cand.id,
            interview_id=interview.id,
            idempotency_key=idempotency_key,
        )

        # Notify HR of scheduled event
        hr_email = get_hr_notification_email()
        if hr_email and hr_email != cand.email:
            hr_subject = f"[HR Notification] Interview Scheduled: {candidate_name} ({job_title})"
            hr_html = build_hr_notification_email(
                event_title=f"Interview Scheduled: {candidate_name}",
                event_type="Interview Scheduled",
                details={
                    "Candidate": candidate_name,
                    "Candidate Email": cand.email,
                    "Position": job_title,
                    "Round": round_name,
                    "When": scheduled_at_str,
                    "Interviewer": interviewer_name,
                    "Meeting Link": meeting_link,
                },
                action_url=f"{get_frontend_url()}",
            )
            record_and_dispatch_notification(
                db=db,
                recipient=hr_email,
                notification_type="hr_event",
                subject=hr_subject,
                body_html=hr_html,
                candidate_id=cand.id,
                interview_id=interview.id,
                idempotency_key=f"hr_scheduled_alert_{interview.id}",
            )

        return log_entry
    finally:
        if close_db:
            db.close()


def send_interview_reminder_notification(
    interview_id: int,
    db: Optional[Session] = None,
    force: bool = False,
) -> Optional[NotificationLog]:
    """
    Requirement 2.B: 24-Hour Interview Reminder.
    Prevents duplicates via idempotency key and updates reminder_sent in PostgreSQL.
    If force=True (manual Remind button clicked), triggers immediate dispatch.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview or not interview.candidate:
            return None

        # Guard against duplicate automated reminder (unless force is requested)
        if interview.reminder_sent and not force:
            logger.info(f"Interview #{interview_id} already marked reminder_sent=True. Skipping duplicate.")
            return None

        cand = interview.candidate
        job = interview.job
        interviewer = interview.interviewer

        candidate_name = cand.full_name
        job_title = job.title if job else "Position"
        round_name = interview.round_name or "Interview Round"
        duration = interview.duration_minutes
        interviewer_name = interviewer.full_name if interviewer else "Hiring Manager"
        meeting_link = interview.meeting_link
        instructions = interview.instructions

        date_str = format_interview_date(interview.scheduled_at)
        subject = f"Reminder: Your Interview is Coming Up – {date_str}"
        body_html, body_text = build_interview_reminder_email(
            candidate_name=candidate_name,
            job_title=job_title,
            round_name=round_name,
            scheduled_at=interview.scheduled_at,
            duration_minutes=duration,
            interviewer_name=interviewer_name,
            meeting_link=meeting_link,
            instructions=instructions,
        )

        idempotency_key = (
            f"interview_reminder_manual_{interview.id}_{int(datetime.now(timezone.utc).timestamp())}"
            if force
            else f"interview_reminder_24h_{interview.id}"
        )

        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=cand.email,
            notification_type="interview_reminder",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            candidate_id=cand.id,
            interview_id=interview.id,
            idempotency_key=idempotency_key,
            force=force,
        )

        # Update interview model reminder status if sent successfully
        if log_entry and log_entry.status == "sent":
            interview.reminder_sent = True
            interview.reminder_sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()

        return log_entry
    finally:
        if close_db:
            db.close()


def send_interview_rescheduled_notification(
    interview_id: int,
    old_time: Optional[datetime] = None,
    reason: Optional[str] = None,
    db: Optional[Session] = None,
) -> Optional[NotificationLog]:
    """
    Requirement 2.D: Triggered when interview time/date changes.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview or not interview.candidate:
            return None

        cand = interview.candidate
        job = interview.job
        interviewer = interview.interviewer

        candidate_name = cand.full_name
        job_title = job.title if job else "Position"
        round_name = interview.round_name or "Interview Round"
        old_time_str = old_time.strftime("%A, %B %d, %Y at %I:%M %p") if old_time else None
        new_time_str = interview.scheduled_at.strftime("%A, %B %d, %Y at %I:%M %p")
        duration = interview.duration_minutes
        interviewer_name = interviewer.full_name if interviewer else "Hiring Manager"
        meeting_link = interview.meeting_link
        instructions = interview.instructions

        # Reset reminder flag if rescheduled to a new future time
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if interview.scheduled_at > (now + timedelta(hours=24)):
            interview.reminder_sent = False
            interview.reminder_sent_at = None
            db.commit()

        new_date_str = format_interview_date(interview.scheduled_at)
        new_time_str = format_interview_time(interview.scheduled_at)

        subject = "Interview Rescheduled – Updated Interview Details"
        body_html, body_text = build_interview_rescheduled_email(
            candidate_name=candidate_name,
            job_title=job_title,
            round_name=round_name,
            new_date_str=new_date_str,
            new_time_str=new_time_str,
            interviewer_name=interviewer_name,
            meeting_link=meeting_link,
            reason=reason,
        )

        sched_ts = int(interview.scheduled_at.timestamp()) if hasattr(interview.scheduled_at, "timestamp") else int(datetime.utcnow().timestamp())
        now_ts = int(datetime.utcnow().timestamp())
        idempotency_key = f"interview_rescheduled_{interview.id}_{sched_ts}_{now_ts}"
        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=cand.email,
            notification_type="interview_rescheduled",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            candidate_id=cand.id,
            interview_id=interview.id,
            idempotency_key=idempotency_key,
        )
        return log_entry
    finally:
        if close_db:
            db.close()


def send_interview_cancelled_notification(
    interview_id: int,
    reason: Optional[str] = None,
    db: Optional[Session] = None,
) -> Optional[NotificationLog]:
    """
    Requirement 2.D: Triggered when interview is cancelled.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview or not interview.candidate:
            return None

        cand = interview.candidate
        job = interview.job
        interviewer = interview.interviewer

        candidate_name = cand.full_name
        job_title = job.title if job else "Position"
        round_name = interview.round_name or "Interview Round"
        previous_date_str = format_interview_date(interview.scheduled_at)
        previous_time_str = format_interview_time(interview.scheduled_at)

        subject = f"Interview Cancellation – {job_title}"
        body_html, body_text = build_interview_cancelled_email(
            candidate_name=candidate_name,
            job_title=job_title,
            round_name=round_name,
            previous_date_str=previous_date_str,
            previous_time_str=previous_time_str,
            reason=reason,
        )

        idempotency_key = f"interview_cancelled_{interview.id}"
        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=cand.email,
            notification_type="interview_cancelled",
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            candidate_id=cand.id,
            interview_id=interview.id,
            idempotency_key=idempotency_key,
        )
        return log_entry
    finally:
        if close_db:
            db.close()


def send_candidate_status_notification(
    candidate_id: int,
    new_status: str,
    job_id: Optional[int] = None,
    notes: Optional[str] = None,
    db: Optional[Session] = None,
) -> Optional[NotificationLog]:
    """
    Requirement 2.C: Application Status Updates (Shortlisted, Selected, Rejected).
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            return None

        # Determine job title from latest interview or specified job_id
        job_title = "Open Position"
        if job_id:
            from ..models import JobPosition
            target_job = db.query(JobPosition).filter(JobPosition.id == job_id).first()
            if target_job:
                job_title = target_job.title
        elif candidate.interviews:
            latest_iv = candidate.interviews[-1]
            if latest_iv.job:
                job_title = latest_iv.job.title

        norm_status = new_status.lower().strip()
        if norm_status not in ["shortlisted", "selected", "rejected"]:
            logger.info(f"Status '{norm_status}' is not a notified candidate stage. Skipping email.")
            return None

        subject_map = {
            "shortlisted": f"Application Shortlisted: {job_title}",
            "selected": f"Congratulations! Selection Update for {job_title}",
            "rejected": f"Update regarding your application for {job_title}",
        }
        subject = subject_map.get(norm_status, f"Application Status Update: {job_title}")

        body_html = build_status_update_email(
            candidate_name=candidate.full_name,
            job_title=job_title,
            new_status=norm_status,
            notes=notes,
        )

        idempotency_key = f"candidate_status_{candidate.id}_{norm_status}_{int(datetime.now(timezone.utc).timestamp() // 60)}"
        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=candidate.email,
            notification_type="status_update",
            subject=subject,
            body_html=body_html,
            candidate_id=candidate.id,
            idempotency_key=idempotency_key,
        )
        return log_entry
    finally:
        if close_db:
            db.close()


def send_hr_new_candidate_notification(candidate_id: int, db: Optional[Session] = None) -> Optional[NotificationLog]:
    """
    Requirement 2.E: Notify HR when a new candidate applies or is registered.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if not candidate:
            return None

        hr_email = get_hr_notification_email()
        if not hr_email:
            return None

        subject = f"[HR Alert] New Candidate Registered: {candidate.full_name}"
        body_html = build_hr_notification_email(
            event_title=f"New Candidate Profile Created",
            event_type="New Application",
            details={
                "Full Name": candidate.full_name,
                "Email Address": candidate.email,
                "Phone": candidate.phone or "Not provided",
                "Resume Link": candidate.resume_url or "Not uploaded",
                "Created At": candidate.created_at.strftime("%Y-%m-%d %H:%M:%S") if candidate.created_at else "Just now",
            },
            action_url=f"{get_frontend_url()}",
        )

        idempotency_key = f"hr_new_candidate_{candidate.id}"
        log_entry = record_and_dispatch_notification(
            db=db,
            recipient=hr_email,
            notification_type="hr_new_candidate",
            subject=subject,
            body_html=body_html,
            candidate_id=candidate.id,
            idempotency_key=idempotency_key,
        )
        return log_entry
    finally:
        if close_db:
            db.close()


def send_test_notification(to_email: str, notes: Optional[str] = None, db: Optional[Session] = None) -> NotificationLog:
    """
    Send test email for HR/Admin configuration verification.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        subject = "ROSTER Test Notification: Gmail SMTP Verification"
        body_html = build_test_email(to_email, notes)
        return record_and_dispatch_notification(
            db=db,
            recipient=to_email,
            notification_type="test_email",
            subject=subject,
            body_html=body_html,
            idempotency_key=None,
        )
    finally:
        if close_db:
            db.close()


def retry_failed_notification(log_id: int, db: Optional[Session] = None) -> Optional[NotificationLog]:
    """
    Retry sending a failed or past notification.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        log_entry = db.query(NotificationLog).filter(NotificationLog.id == log_id).first()
        if not log_entry:
            return None

        log_entry.retry_count += 1
        success, error_msg = send_raw_email(
            to_email=log_entry.recipient,
            subject=log_entry.subject,
            html_content=log_entry.body_html or "<p>Notification content</p>",
        )

        if success:
            log_entry.status = "sent"
            log_entry.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            log_entry.error_message = None
        else:
            log_entry.status = "failed"
            log_entry.error_message = error_msg

        db.commit()
        db.refresh(log_entry)
        return log_entry
    finally:
        if close_db:
            db.close()


# ============================================================================
# 24-HOUR REMINDER BACKGROUND SCHEDULER
# ============================================================================

def check_and_send_interview_reminders() -> int:
    """
    Periodic job: Inspects scheduled interviews in PostgreSQL.
    Identifies interviews scheduled between now and (now + 24 hours), or in the past
    2 hours (handling server restarts / downtime), where status is SCHEDULED
    and reminder_sent is FALSE.
    Dispatches reminder email and marks reminder_sent=True.
    Returns the count of reminders processed.
    """
    logger.info("Executing periodic 24-hour interview reminder check...")
    processed_count = 0

    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reminder_window_start = now - timedelta(hours=2)   # Catch up if missed during downtime
        reminder_window_end = now + timedelta(hours=24)     # Upcoming in next 24 hours

        interviews_to_remind = (
            db.query(Interview)
            .filter(
                Interview.status == InterviewStatus.SCHEDULED,
                Interview.reminder_sent == False,
                Interview.scheduled_at >= reminder_window_start,
                Interview.scheduled_at <= reminder_window_end,
            )
            .all()
        )

        for iv in interviews_to_remind:
            try:
                logger.info(f"Dispatching 24h reminder for interview #{iv.id} (Scheduled at: {iv.scheduled_at})")
                send_interview_reminder_notification(iv.id, db=db)
                processed_count += 1
            except Exception as e:
                logger.error(f"Error sending reminder for interview #{iv.id}: {e}")

    logger.info(f"Interview reminder check complete. Processed {processed_count} reminder(s).")
    return processed_count


def start_email_scheduler():
    """
    Start the APScheduler background daemon to run interview reminder checks.
    Runs every 15 minutes, and executes an immediate check on startup.
    """
    global _email_scheduler
    if _email_scheduler is not None and _email_scheduler.running:
        return _email_scheduler

    try:
        _email_scheduler = BackgroundScheduler(daemon=True)
        # Schedule periodic check every 15 minutes
        _email_scheduler.add_job(
            check_and_send_interview_reminders,
            "interval",
            minutes=15,
            id="interview_24h_reminders",
            replace_existing=True,
        )
        _email_scheduler.start()
        logger.info("Email Background Scheduler started successfully (Interval: 15m).")

        # Run immediate check for missed reminders on startup
        try:
            check_and_send_interview_reminders()
        except Exception as startup_err:
            logger.warning(f"Startup reminder check notice: {startup_err}")

        return _email_scheduler
    except Exception as exc:
        logger.error(f"Failed to start APScheduler: {exc}")
        return None


def shutdown_email_scheduler():
    """Cleanly stop background scheduler during application shutdown."""
    global _email_scheduler
    if _email_scheduler is not None and _email_scheduler.running:
        try:
            _email_scheduler.shutdown(wait=False)
            logger.info("Email Background Scheduler stopped.")
        except Exception:
            pass
        _email_scheduler = None
