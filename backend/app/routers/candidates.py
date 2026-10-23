import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db
from ..services import email_service

router = APIRouter(prefix="/candidates", tags=["Candidates"])

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads" / "resumes"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".rtf"}


@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    """Upload a resume file and return its public URL."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Sanitize and create unique filename
    raw_name = Path(file.filename or "resume.pdf").name
    safe_filename = f"{uuid.uuid4().hex[:10]}_{raw_name}"
    dest_path = UPLOAD_DIR / safe_filename

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "resume_url": f"/uploads/resumes/{safe_filename}",
        "filename": raw_name,
    }


@router.post("/", response_model=schemas.CandidateOut, status_code=status.HTTP_201_CREATED)
def create_candidate(
    payload: schemas.CandidateCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing = crud.get_candidate_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="A candidate with this email already exists")
    candidate = crud.create_candidate(db, payload)

    # Requirement 2.E: Notify configured HR email when a new candidate applies
    background_tasks.add_task(email_service.send_hr_new_candidate_notification, candidate.id)

    return candidate


@router.get("/", response_model=list[schemas.CandidateOut])
def list_candidates(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_candidates(db, skip=skip, limit=limit)


@router.get("/{candidate_id}", response_model=schemas.CandidateOut)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.patch("/{candidate_id}", response_model=schemas.CandidateOut)
def update_candidate(
    candidate_id: int,
    payload: schemas.CandidateUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    old_status = candidate.status
    updated = crud.update_candidate(db, candidate, payload)

    # If status changed, send notification (Shortlisted / Selected / Rejected)
    if payload.status and payload.status != old_status:
        background_tasks.add_task(
            email_service.send_candidate_status_notification,
            candidate_id=updated.id,
            new_status=payload.status,
        )

    return updated


@router.patch("/{candidate_id}/status", response_model=schemas.CandidateOut)
def update_candidate_status(
    candidate_id: int,
    payload: schemas.CandidateStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Requirement 2.C: Update candidate pipeline status (Shortlisted, Selected, Rejected)
    and dispatch professional notification email.
    """
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate = crud.update_candidate_status(
        db,
        candidate,
        payload.status,
        job_id=payload.job_id,
        notes=payload.notes,
    )

    # Dispatch status email in background
    background_tasks.add_task(
        email_service.send_candidate_status_notification,
        candidate_id=candidate.id,
        new_status=candidate.status,
        job_id=payload.job_id,
        notes=payload.notes,
    )

    return candidate


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = crud.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    crud.delete_candidate(db, candidate)
    return None

