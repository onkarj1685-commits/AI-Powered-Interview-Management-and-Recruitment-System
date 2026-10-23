"""
AI-Powered Interview Management and Recruitment System - FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload

Interactive API docs are available at /docs once running.
"""
import sys
from pathlib import Path

# Ensure the backend directory and project root are in sys.path so direct execution works without import errors
_app_dir = Path(__file__).resolve().parent
_backend_dir = _app_dir.parent
_project_root = _backend_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

# Support both package imports and direct script execution
try:
    from . import crud, models
    from .database import engine, SessionLocal, ensure_schema_compatibility
    from .routers import (
        candidates,
        jobs,
        interviewers,
        interviews,
        dashboard,
        ai_assistant,
        auth,
        screening,
        analyzer,
        notifications,
        analytics,
    )
    from .routers.auth import hash_password
    from .services import email_service
except (ImportError, ValueError):
    from app import crud, models
    from app.database import engine, SessionLocal, ensure_schema_compatibility
    from app.routers import (
        candidates,
        jobs,
        interviewers,
        interviews,
        dashboard,
        ai_assistant,
        auth,
        screening,
        analyzer,
        notifications,
        analytics,
    )
    from app.routers.auth import hash_password
    from app.services import email_service

# Define frontend and uploads directories
_frontend_dir = _project_root / "frontend"
_uploads_dir = _project_root / "uploads"
(_uploads_dir / "resumes").mkdir(parents=True, exist_ok=True)

# Create all tables if they don't exist yet.
# (For a production system you'd use Alembic migrations instead of create_all.)
models.Base.metadata.create_all(bind=engine)
ensure_schema_compatibility(engine)


# Seed default admin user on startup if no users exist
try:
    with SessionLocal() as _seed_db:
        crud.seed_default_user_if_empty(_seed_db, hash_password("Admin123!"))
except Exception as _seed_err:
    print("Notice on user seeding:", _seed_err)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start APScheduler for 24h reminders
    try:
        email_service.start_email_scheduler()
    except Exception as _sched_err:
        print("Email Scheduler startup notice:", _sched_err)
    yield
    # Shutdown: Cleanly stop scheduler
    try:
        email_service.shutdown_email_scheduler()
    except Exception as _sched_down:
        print("Email Scheduler shutdown notice:", _sched_down)


app = FastAPI(
    title="AI-Powered Interview Management and Recruitment System",
    description="API for managing candidates, job positions, interviewers, "
    "interviews, and feedback throughout the hiring pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the frontend (served separately) to call this API during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(candidates.router)
app.include_router(jobs.router)
app.include_router(interviewers.router)
app.include_router(interviews.router)
app.include_router(dashboard.router)
app.include_router(ai_assistant.router)
app.include_router(screening.router)
app.include_router(analyzer.router)
app.include_router(notifications.router)
app.include_router(analytics.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}


@app.get("/api", tags=["Health"])
def api_status():
    return {"status": "ok", "service": "interview-management-system"}


@app.get("/login", include_in_schema=False)
def serve_login():
    login_file = _frontend_dir / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    return FileResponse(_frontend_dir / "index.html")


@app.get("/register", include_in_schema=False)
def serve_register():
    reg_file = _frontend_dir / "register.html"
    if reg_file.exists():
        return FileResponse(reg_file)
    return FileResponse(_frontend_dir / "login.html")


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    return FileResponse(_frontend_dir / "index.html")


@app.get("/analytics", include_in_schema=False)
def serve_analytics():
    return FileResponse(_frontend_dir / "index.html")


# Mount uploads directory for resume files
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# Serve frontend static UI (HTML/CSS/JS) if frontend directory exists
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
else:
    @app.get("/", tags=["Health"])
    def root():
        return {"status": "ok", "service": "interview-management-system"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

