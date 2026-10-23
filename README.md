# AI-Powered Interview Management and Recruitment System

An intelligent, full-stack recruitment platform designed to simplify and improve the hiring process. The system helps HR teams manage job positions, candidates, interviewers, interview scheduling, resume screening, and recruitment analytics through a centralized application.

## Key Features

- **AI Resume Analysis:** Extract relevant information and skills from uploaded resumes and assist with candidate evaluation.
- **AI Resume Screening:** Compare candidate profiles with job requirements and support resume matching.
- **Candidate Management:** Maintain candidate information and track recruitment activities.
- **Job Position Management:** Manage job titles, departments, job descriptions, and openings.
- **Interview Management:** Schedule interviews and manage interview status and feedback.
- **Interviewer Management:** Maintain interviewer information and assignments.
- **Recruitment Analytics:** Analyze recruitment activity, candidate distribution, and hiring performance.
- **Authentication:** Support application login and Google authentication where configured.
- **Email Notifications:** Support registration and recruitment-related email communication where configured.
- **REST API:** Provide backend endpoints for application operations.

*Note: Feature availability depends on the current implementation and configuration of the application.*

## Technology Stack

| Component | Technologies |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Frontend | HTML, CSS, JavaScript |
| Data Validation | Pydantic |
| Testing | pytest, FastAPI TestClient |
| Authentication | Application authentication and Google OAuth, where configured |
| Deployment Support | Docker and Docker Compose |

## Project Structure

```text
interview_management/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── crud.py
│   │   ├── resume_analyzer.py
│   │   ├── resume_screener.py
│   │   ├── routers/
│   │   │   ├── ai_assistant.py
│   │   │   ├── analytics.py
│   │   │   ├── analyzer.py
│   │   │   ├── auth.py
│   │   │   ├── candidates.py
│   │   │   ├── dashboard.py
│   │   │   ├── interviewers.py
│   │   │   ├── interviews.py
│   │   │   ├── jobs.py
│   │   │   ├── notifications.py
│   │   │   └── screening.py
│   │   └── services/
│   ├── migrations/
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   └── app.js
├── docker-compose.yml
├── .gitignore
└── README.md
```

## Prerequisites

Install the following before running the application manually:

- Python 3.12 or another version supported by the project's dependencies
- PostgreSQL
- Git
- A modern web browser

Docker and Docker Compose can be used if the provided Docker configuration supports your environment.

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/onkarj1685-commits/AI-Powered-Interview-Management-and-Recruitment-System.git
cd AI-Powered-Interview-Management-and-Recruitment-System
```

### 2. Create a Python virtual environment

On Windows Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install backend dependencies

```bat
cd backend
pip install -r requirements.txt
```

### 4. Configure environment variables

Create your local `.env` file using the provided example:

```bat
copy .env.example .env
```

Open the new `.env` file and configure the database connection and any required authentication, email, or AI service credentials.

Create the PostgreSQL database and ensure the connection settings match your local configuration.

**Security:** Never upload real passwords, API keys, OAuth client secrets, or other credentials to GitHub. Keep these values in local environment files.

### 5. Start the backend

From the `backend` directory, run:

```bat
python -m uvicorn app.main:app --reload
```

If the configuration is correct, the API should be available at:

- API: http://localhost:8000
- Interactive API documentation: http://localhost:8000/docs

### 6. Open the frontend

Open `frontend/index.html` in your browser, or serve the frontend from its directory:

```bat
cd ..\frontend
python -m http.server 5500
```

Then visit http://localhost:5500.

Ensure the frontend API configuration points to the correct backend URL. If browser requests fail, check CORS settings and the API base URL.

## Running with Docker

From the repository root, run:

```bash
docker compose up --build
```

This uses the services defined in `docker-compose.yml`. Configure the required environment variables and database settings before starting the application.

## Running Tests

From the repository root:

```bat
cd backend
pytest tests/ -v
```

The tests and their database configuration determine whether PostgreSQL or an isolated test database is used. Check the test configuration before assuming that no database setup is required.

## API Documentation

FastAPI provides interactive API documentation at:

http://localhost:8000/docs

Use this page to inspect the routes registered by the application, review request and response schemas, and test supported endpoints.

The API includes modules for candidates, job positions, interviewers, interviews, resume analysis, screening, authentication, notifications, and analytics. The exact endpoints depend on the routes registered in the current version.

## Security and Deployment Notes

- Keep environment files and credentials out of version control.
- Configure authentication and authorization before exposing the application publicly.
- Restrict access to candidate resumes and personal information.
- Configure HTTPS and appropriate CORS rules for production.
- Use database migrations to manage schema changes as the project evolves.
- Test the complete application and deployment configuration before production use.

## Future Enhancements

- Improve AI-based candidate-job matching.
- Add more recruitment performance metrics and visualizations.
- Enhance automated interview reminders and rescheduling notifications.
- Improve reporting and CSV/PDF export capabilities.
- Add production deployment, monitoring, and stronger access controls.

## Project Information

**Project Title:** AI-Powered Interview Management and Recruitment System

**Project Type:** B.Tech Computer Science and Engineering Final-Year Project

**Purpose:** To simplify recruitment workflows by combining interview management, resume analysis, candidate screening, and recruitment insights in a centralized platform.
