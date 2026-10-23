from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/interviewers", tags=["Interviewers"])


@router.post("/", response_model=schemas.InterviewerOut, status_code=status.HTTP_201_CREATED)
def create_interviewer(payload: schemas.InterviewerCreate, db: Session = Depends(get_db)):
    return crud.create_interviewer(db, payload)


@router.get("/", response_model=list[schemas.InterviewerOut])
def list_interviewers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_interviewers(db, skip=skip, limit=limit)


@router.get("/{interviewer_id}", response_model=schemas.InterviewerOut)
def get_interviewer(interviewer_id: int, db: Session = Depends(get_db)):
    interviewer = crud.get_interviewer(db, interviewer_id)
    if not interviewer:
        raise HTTPException(status_code=404, detail="Interviewer not found")
    return interviewer


@router.patch("/{interviewer_id}", response_model=schemas.InterviewerOut)
def update_interviewer(
    interviewer_id: int, payload: schemas.InterviewerUpdate, db: Session = Depends(get_db)
):
    interviewer = crud.get_interviewer(db, interviewer_id)
    if not interviewer:
        raise HTTPException(status_code=404, detail="Interviewer not found")
    return crud.update_interviewer(db, interviewer, payload)


@router.delete("/{interviewer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interviewer(interviewer_id: int, db: Session = Depends(get_db)):
    interviewer = crud.get_interviewer(db, interviewer_id)
    if not interviewer:
        raise HTTPException(status_code=404, detail="Interviewer not found")
    crud.delete_interviewer(db, interviewer)
    return None
