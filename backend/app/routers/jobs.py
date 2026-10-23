from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/jobs", tags=["Job Positions"])


@router.post("/", response_model=schemas.JobPositionOut, status_code=status.HTTP_201_CREATED)
def create_job(payload: schemas.JobPositionCreate, db: Session = Depends(get_db)):
    return crud.create_job(db, payload)


@router.get("/", response_model=list[schemas.JobPositionOut])
def list_jobs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_jobs(db, skip=skip, limit=limit)


@router.get("/{job_id}", response_model=schemas.JobPositionOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job position not found")
    return job


@router.patch("/{job_id}", response_model=schemas.JobPositionOut)
def update_job(job_id: int, payload: schemas.JobPositionUpdate, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job position not found")
    return crud.update_job(db, job, payload)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job position not found")
    crud.delete_job(db, job)
    return None
