"""
Database configuration for the AI-Powered Interview Management and Recruitment System.

Uses SQLAlchemy with PostgreSQL. The connection string is read from the
DATABASE_URL environment variable so the same code works locally, in
Docker, and in tests (where we override it with SQLite).
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Search for .env in project root and backend directory (backend takes precedence)
    _backend_dir = Path(__file__).resolve().parent.parent
    load_dotenv(_backend_dir.parent / ".env")
    load_dotenv(_backend_dir / ".env", override=True)
except ImportError:
    pass

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://interview_user:interview_pass@localhost:5432/interview_db",
)

_engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    # `check_same_thread` is only needed for SQLite (used in tests/local dev).
    # `StaticPool` keeps a single shared connection alive so an in-memory
    # SQLite database persists across sessions within the same process.
    from sqlalchemy.pool import StaticPool

    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in DATABASE_URL:
        _engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_schema_compatibility(db_engine):
    """
    Ensure newly added User columns exist if the users table was already created in PostgreSQL.
    Safely executes ALTER TABLE ADD COLUMN IF NOT EXISTS statements.
    """
    try:
        if db_engine.dialect.name == "postgresql":
            with db_engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(120);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(120);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture VARCHAR(500);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'HR/User';"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;"))
                conn.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;"))
                conn.execute(text("ALTER TABLE users ALTER COLUMN username DROP NOT NULL;"))

                # Candidates table migrations
                conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'applied';"))
                conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS job_id INTEGER REFERENCES job_positions(id) ON DELETE SET NULL;"))
                conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS selection_timestamp TIMESTAMP;"))

                # Candidate stage history table migration
                conn.execute(text("""
                CREATE TABLE IF NOT EXISTS candidate_stage_history (
                    id SERIAL PRIMARY KEY,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    stage VARCHAR(50) NOT NULL,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                );
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_candidate_stage_history_candidate_id ON candidate_stage_history (candidate_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_candidate_stage_history_stage ON candidate_stage_history (stage);"))

                # Interviews table migrations
                conn.execute(text("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS meeting_link VARCHAR(500);"))
                conn.execute(text("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS instructions TEXT;"))
                conn.execute(text("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN DEFAULT FALSE;"))
                conn.execute(text("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMP;"))

                # Ensure departments have no accidental leading/trailing whitespace
                conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'job_positions') THEN
                        UPDATE job_positions SET department = TRIM(department) WHERE department IS NOT NULL AND department != TRIM(department);
                    END IF;
                END $$;
                """))
                conn.commit()
    except Exception as err:
        print("Schema compatibility notice:", err)


def get_db():
    """FastAPI dependency that yields a database session and closes it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

