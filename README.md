# AI-Powered Interview Management and Recruitment System

An intelligent, modern full-stack platform for running an end-to-end recruitment pipeline: AI resume analysis, automated screening, candidate management, job positions, interviewers, scheduled interviews, and feedback scorecards.

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend:** Vanilla HTML/CSS/JS (no build step)
- **Tests:** pytest + FastAPI's TestClient, run against an isolated in-memory SQLite DB

## Project layout

```
interview_management/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, router registration
│   │   ├── database.py        # SQLAlchemy engine/session setup
│   │   ├── models.py          # ORM models (Candidate, JobPosition, Interviewer, Interview, Feedback)
│   │   ├── schemas.py         # Pydantic request/response schemas
│   │   ├── crud.py            # DB access functions used by the routers
│   │   └── routers/
│   │       ├── candidates.py
│   │       ├── jobs.py
│   │       ├── interviewers.py
│   │       └── interviews.py  # includes nested /interviews/{id}/feedback endpoints
│   ├── tests/                 # pytest suite (30 tests)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── index.html
│   └── app.js
├── docker-compose.yml          # Postgres + API, one command
└── README.md
```

## Data model

- **Candidate** — name, email, phone, resume URL
- **JobPosition** — title, department, description, status (open / on_hold / closed)
- **Interviewer** — name, email, title
- **Interview** — links a candidate, job, and interviewer; has a scheduled time,
  duration, round name, and status (scheduled / completed / cancelled / no_show)
- **Feedback** — one per interview; score (1–5), recommendation
  (strong_yes / yes / no / strong_no), strengths, concerns, notes. Submitting
  feedback automatically marks the interview as `completed`.

## Running locally

### Option A — Docker (easiest)

```bash
docker compose up --build
```

This starts PostgreSQL and the API together. The API will be available at
`http://localhost:8000`, with interactive docs at `http://localhost:8000/docs`.

Then open `frontend/index.html` directly in your browser (or serve it with
`python -m http.server` from inside the `frontend/` folder).

### Option B — Run the backend manually

1. Start a local PostgreSQL instance and create a database, or point
   `DATABASE_URL` at any Postgres instance you already have:

   ```bash
   export DATABASE_URL="postgresql://interview_user:interview_pass@localhost:5432/interview_db"
   ```

2. Install dependencies and run the API:

   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```

   Tables are created automatically on startup.

3. Open `frontend/index.html` in a browser. It talks to `http://localhost:8000`
   by default — change `API_BASE` at the top of `frontend/app.js` if your API
   runs elsewhere.

## Running the tests

Tests don't need PostgreSQL or Docker — they run against an isolated
in-memory SQLite database:

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

30 tests cover candidates, jobs, interviewers, interviews, and feedback,
including validation errors (bad email, out-of-range score), 404s, duplicate
prevention (duplicate candidate email, duplicate feedback for one interview),
and the business rule that submitting feedback marks an interview completed.

## API overview

All endpoints are under the API root and documented interactively at `/docs`.

| Resource | Endpoints |
|---|---|
| Candidates | `POST /candidates/`, `GET /candidates/`, `GET /candidates/{id}`, `PATCH /candidates/{id}`, `DELETE /candidates/{id}` |
| Job positions | `POST /jobs/`, `GET /jobs/`, `GET /jobs/{id}`, `PATCH /jobs/{id}`, `DELETE /jobs/{id}` |
| Interviewers | `POST /interviewers/`, `GET /interviewers/`, `GET /interviewers/{id}`, `PATCH /interviewers/{id}`, `DELETE /interviewers/{id}` |
| Interviews | `POST /interviews/`, `GET /interviews/` (filterable by `candidate_id`, `interviewer_id`, `status_filter`), `GET /interviews/{id}` (nested candidate/job/interviewer), `PATCH /interviews/{id}`, `DELETE /interviews/{id}` |
| Feedback | `POST /interviews/{id}/feedback`, `GET /interviews/{id}/feedback` |

## Notes / possible next steps

- No authentication is included — anyone who can reach the API can use it.
  Add an auth layer (e.g. OAuth2 + JWT) before deploying this anywhere real.
- `models.Base.metadata.create_all()` is used for simplicity. For real
  deployments, switch to [Alembic](https://alembic.sqlalchemy.org/) migrations
  so schema changes are tracked and reversible.
- The frontend is intentionally framework-free for easy inspection; it would
  map cleanly onto React/Vue if the project grows.
