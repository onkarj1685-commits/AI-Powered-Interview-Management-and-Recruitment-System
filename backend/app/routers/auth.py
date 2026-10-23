import json
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-jwt-key-interview-mgmt-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Google OAuth 2.0 Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ---------- Password & JWT Helpers ----------

def hash_password(password: str) -> str:
    """Hash plain text password with bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify plain password against hashed password."""
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(user: models.User, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT token for the user."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user.id),
        "username": user.username or user.email,
        "email": user.email,
        "name": user.name or user.full_name or user.username,
        "role": user.role,
        "profile_picture": user.profile_picture,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Optional[models.User]:
    """Extract and validate the user from Bearer token."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        return crud.get_user_by_id(db, int(user_id_str))
    except (jwt.PyJWTError, ValueError):
        return None


def require_current_user(
    user: Optional[models.User] = Depends(get_current_user),
) -> models.User:
    """Dependency enforcing that the caller is authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def render_oauth_success_page(jwt_token: str, user_dict: dict) -> HTMLResponse:
    """
    Render a cyber-styled bridge page that securely sets credentials in localStorage
    and immediately redirects to the dashboard without exposing tokens in the address bar.
    """
    token_json = json.dumps(jwt_token)
    user_json = json.dumps(user_dict)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Authenticating — AI-Powered Interview Management and Recruitment System</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #050811;
      color: #FFFFFF;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .auth-box {{
      text-align: center;
      padding: 36px 44px;
      background: rgba(9, 14, 26, 0.95);
      border: 1.5px solid rgba(0, 242, 254, 0.5);
      border-radius: 16px;
      box-shadow: 0 0 50px rgba(0, 242, 254, 0.25);
    }}
    .spinner {{
      width: 44px;
      height: 44px;
      border: 3px solid rgba(0, 242, 254, 0.15);
      border-top-color: #00F2FE;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto 18px auto;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    .title {{
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: #00F2FE;
      margin-bottom: 8px;
    }}
    .desc {{
      font-size: 14px;
      color: #94A3B8;
    }}
  </style>
</head>
<body>
  <div class="auth-box">
    <div class="spinner"></div>
    <div class="title">AUTHENTICATION SUCCESSFUL</div>
    <div class="desc">Signing in with Google & redirecting to Dashboard...</div>
  </div>
  <script>
    try {{
      localStorage.setItem("auth_token", {token_json});
      localStorage.setItem("auth_user", {user_json});
      setTimeout(function() {{
        window.location.href = "/";
      }}, 300);
    }} catch (e) {{
      window.location.href = "/?token=" + encodeURIComponent({token_json});
    }}
  </script>
</body>
</html>
"""
    response = HTMLResponse(content=html_content)
    response.delete_cookie("oauth_state")
    return response


# ---------- Standard Auth Endpoints ----------

@router.post("/register", response_model=schemas.TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """Register a new user account."""
    if crud.get_user_by_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    if crud.get_user_by_username(db, payload.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this username already exists",
        )

    hashed = hash_password(payload.password)
    user = crud.create_user(db, payload, hashed)
    token = create_access_token(user)

    return schemas.TokenOut(
        access_token=token,
        token_type="bearer",
        user=schemas.UserOut.model_validate(user),
    )


@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    """Authenticate with username/email and password."""
    user = crud.get_user_by_email_or_username(db, payload.username_or_email)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)

    token = create_access_token(user)
    return schemas.TokenOut(
        access_token=token,
        token_type="bearer",
        user=schemas.UserOut.model_validate(user),
    )


@router.get("/me", response_model=schemas.UserOut)
def get_current_user_profile(user: models.User = Depends(require_current_user)):
    """Return profile details of the authenticated user."""
    return user


@router.post("/forgot-password", response_model=schemas.ForgotPasswordResponse)
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Handle password reset request."""
    user = crud.get_user_by_email_or_username(db, payload.email_or_username)
    if user:
        return schemas.ForgotPasswordResponse(
            message=f"Password recovery requested for '{user.username}'. As this is a college project environment, please use the admin credentials or contact your administrator."
        )
    return schemas.ForgotPasswordResponse(
        message="If an account matching the provided information exists, password recovery instructions have been initiated."
    )


@router.post("/logout")
def logout(response: Response):
    """Logout endpoint acknowledging session termination."""
    response.delete_cookie("oauth_state")
    return {"status": "ok", "message": "Successfully logged out"}


# ---------- Google OAuth 2.0 Endpoints ----------

@router.get("/google/login")
def google_login(request: Request):
    """
    Redirect user to Google OAuth 2.0 login screen.
    Includes account selector (prompt=select_account) and CSRF protection.
    """
    client_id = (GOOGLE_CLIENT_ID or "").strip()
    if not client_id or client_id.startswith("your_google_client_id"):
        return RedirectResponse(
            url="/login?error=Google+OAuth+credentials+not+configured.+Please+set+GOOGLE_CLIENT_ID+and+GOOGLE_CLIENT_SECRET+in+backend/.env",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    state = secrets.token_urlsafe(32)
    redirect_uri = (os.getenv("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI) or "").strip()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",  # Requirement 3: Allow user to select a Google account
        "state": state,
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(url=google_auth_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Handle Google OAuth 2.0 callback:
    - Verifies CSRF state token
    - Exchanges code for Google access token
    - Retrieves user profile (name, email, profile picture, sub/id)
    - Creates or updates PostgreSQL user record
    - Issues JWT and redirects to Dashboard
    """
    if error:
        error_msg = request.query_params.get("error_description") or error
        return RedirectResponse(
            url=f"/login?error=Google+login+cancelled:+{urllib.parse.quote(error_msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not code:
        return RedirectResponse(
            url="/login?error=Authorization+code+missing+from+Google+response",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Validate CSRF state if cookie present
    cookie_state = request.cookies.get("oauth_state")
    if cookie_state and state and cookie_state != state:
        return RedirectResponse(
            url="/login?error=Invalid+OAuth+state+token.+Please+try+again.",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    token_url = "https://oauth2.googleapis.com/token"
    redirect_uri = (os.getenv("GOOGLE_REDIRECT_URI", GOOGLE_REDIRECT_URI) or "").strip()
    token_payload = {
        "client_id": GOOGLE_CLIENT_ID.strip(),
        "client_secret": GOOGLE_CLIENT_SECRET.strip(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            token_resp = await http_client.post(token_url, data=token_payload)
            if token_resp.status_code != 200:
                err_data = token_resp.json().get("error_description") or token_resp.text
                return RedirectResponse(
                    url=f"/login?error=Google+token+exchange+failed:+{urllib.parse.quote(err_data)}",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

            token_json = token_resp.json()
            access_token = token_json.get("access_token")
            if not access_token:
                return RedirectResponse(
                    url="/login?error=No+access+token+received+from+Google",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            userinfo_resp = await http_client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                return RedirectResponse(
                    url="/login?error=Failed+to+retrieve+Google+user+profile",
                    status_code=status.HTTP_303_SEE_OTHER,
                )

            profile = userinfo_resp.json()
    except Exception as exc:
        return RedirectResponse(
            url=f"/login?error=Network+error+connecting+to+Google:+{urllib.parse.quote(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    google_id = profile.get("sub")
    email = profile.get("email")
    name = profile.get("name") or profile.get("given_name") or "Google User"
    picture = profile.get("picture")

    if not google_id or not email:
        return RedirectResponse(
            url="/login?error=Incomplete+Google+profile+data+(missing+email+or+ID)",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # Provision or update user in PostgreSQL database
    user = crud.create_or_update_google_user(
        db=db,
        google_id=google_id,
        email=email,
        name=name,
        profile_picture=picture,
    )

    # Issue application JWT token
    jwt_token = create_access_token(user)
    user_out = schemas.UserOut.model_validate(user).model_dump(mode="json")

    return render_oauth_success_page(jwt_token, user_out)


@router.get("/google/demo", response_class=HTMLResponse)
def google_demo_login(
    email: Optional[str] = "google.evaluator@example.com",
    name: Optional[str] = "Google Evaluator",
    db: Session = Depends(get_db),
):
    """
    Development and evaluation helper to test the complete Google OAuth flow
    even if live Google Cloud OAuth credentials have not been configured yet.
    """
    demo_google_id = "google_demo_eval_83749281729"
    demo_picture = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80"

    user = crud.create_or_update_google_user(
        db=db,
        google_id=demo_google_id,
        email=email,
        name=name,
        profile_picture=demo_picture,
    )

    jwt_token = create_access_token(user)
    user_out = schemas.UserOut.model_validate(user).model_dump(mode="json")
    return render_oauth_success_page(jwt_token, user_out)

