"""
Tests for user authentication endpoints: registration, login, JWT validation, and password recovery.
"""
import pytest
from app.routers.auth import hash_password
from app import crud


def test_login_seeded_admin(client, db_session):
    """Verify that default admin account seeded on startup can authenticate."""
    crud.seed_default_user_if_empty(db_session, hash_password("Admin123!"))
    resp = client.post(
        "/auth/login",
        json={"username_or_email": "admin", "password": "Admin123!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "admin"


def test_register_new_user(client):
    """Test registering a brand new user account."""
    payload = {
        "full_name": "Alan Turing",
        "username": "aturing",
        "email": "alan@enigma.org",
        "password": "SecretPassword123!",
        "role": "admin",
    }
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["username"] == "aturing"
    assert data["user"]["email"] == "alan@enigma.org"


def test_register_duplicate_username_fails(client):
    """Duplicate username should be rejected with 400 Bad Request."""
    payload = {
        "full_name": "Test One",
        "username": "dupeuser",
        "email": "dupe1@example.com",
        "password": "Password123!",
    }
    resp1 = client.post("/auth/register", json=payload)
    assert resp1.status_code == 201

    payload2 = {
        "full_name": "Test Two",
        "username": "dupeuser",
        "email": "dupe2@example.com",
        "password": "Password123!",
    }
    resp2 = client.post("/auth/register", json=payload2)
    assert resp2.status_code == 400
    assert "username already exists" in resp2.json()["detail"].lower()


def test_login_with_email_and_username(client):
    """User should be able to log in using either their email or their username."""
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Ada Lovelace",
            "username": "adalove",
            "email": "ada@computing.org",
            "password": "P@ssword123",
        },
    )
    assert reg.status_code == 201

    # Login with username
    login_user = client.post(
        "/auth/login",
        json={"username_or_email": "adalove", "password": "P@ssword123"},
    )
    assert login_user.status_code == 200
    assert "access_token" in login_user.json()

    # Login with email
    login_email = client.post(
        "/auth/login",
        json={"username_or_email": "ada@computing.org", "password": "P@ssword123"},
    )
    assert login_email.status_code == 200
    assert "access_token" in login_email.json()


def test_login_invalid_password(client):
    """Incorrect password returns 401 Unauthorized."""
    client.post(
        "/auth/register",
        json={
            "full_name": "Bjarne Stroustrup",
            "username": "bjarne",
            "email": "bjarne@cpp.org",
            "password": "CorrectPassword123!",
        },
    )
    resp = client.post(
        "/auth/login",
        json={"username_or_email": "bjarne", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"].lower()


def test_login_nonexistent_user(client):
    """Nonexistent username or email returns 401 Unauthorized."""
    resp = client.post(
        "/auth/login",
        json={"username_or_email": "nobody_exists", "password": "Password123!"},
    )
    assert resp.status_code == 401


def test_get_current_user_profile(client):
    """Test accessing protected /auth/me with valid Bearer token."""
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Claude Shannon",
            "username": "shannon",
            "email": "shannon@mit.edu",
            "password": "InformationTheory1!",
        },
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    # Request with valid token
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "shannon"

    # Request without token fails
    anon_resp = client.get("/auth/me")
    assert anon_resp.status_code == 401

    # Request with invalid token fails
    bad_resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.value"})
    assert bad_resp.status_code == 401


def test_forgot_password(client):
    """Test forgot-password request returns helpful instructions."""
    resp = client.post(
        "/auth/forgot-password",
        json={"email_or_username": "admin"},
    )
    assert resp.status_code == 200
    assert "message" in resp.json()


# =============================================================================
# Google OAuth 2.0 Tests
# =============================================================================

from unittest.mock import AsyncMock, patch, MagicMock


def test_logout_endpoint(client):
    """Test /auth/logout endpoint terminates session."""
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_google_login_redirect_not_configured(client, monkeypatch):
    """If Google credentials are not set, redirect to /login with helpful error."""
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_ID", "")
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 303
    assert "login?error=" in resp.headers["location"]


def test_google_login_redirect_configured(client, monkeypatch):
    """If Google credentials are set, redirect to accounts.google.com."""
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_ID", "test-client-id-123.apps.googleusercontent.com")
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert "accounts.google.com" in loc
    assert "client_id=test-client-id-123.apps.googleusercontent.com" in loc
    assert "oauth_state" in resp.cookies


def test_google_callback_creates_new_user(client, db_session, monkeypatch):
    """Google callback with valid token & profile creates a new user with role HR/User."""
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_SECRET", "test-secret")

    # Mock httpx.AsyncClient post and get
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google_access_token_abc"}

    mock_profile_resp = MagicMock()
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = {
        "sub": "google_sub_123456",
        "email": "newuser@google.com",
        "name": "Jane Google",
        "picture": "https://lh3.googleusercontent.com/a/sample.jpg",
    }

    mock_async_client = MagicMock()
    mock_async_client.post = AsyncMock(return_value=mock_token_resp)
    mock_async_client.get = AsyncMock(return_value=mock_profile_resp)
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        resp = client.get(
            "/auth/google/callback?code=mock_code_123&state=test_state",
            cookies={"oauth_state": "test_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 200
    assert "AUTHENTICATION SUCCESSFUL" in resp.text
    assert "localStorage.setItem" in resp.text

    # Verify user created in database
    created = crud.get_user_by_google_id(db_session, "google_sub_123456")
    assert created is not None
    assert created.email == "newuser@google.com"
    assert created.name == "Jane Google"
    assert created.role == "HR/User"
    assert created.profile_picture == "https://lh3.googleusercontent.com/a/sample.jpg"
    assert created.last_login is not None


def test_google_callback_existing_user_updates(client, db_session, monkeypatch):
    """Google callback for existing user updates google_id, profile picture, and last_login."""
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.routers.auth.GOOGLE_CLIENT_SECRET", "test-secret")

    # Create user first via standard registration
    client.post(
        "/auth/register",
        json={
            "full_name": "Pre Existing",
            "username": "preexisting",
            "email": "preexisting@example.com",
            "password": "Password123!",
            "role": "HR/User",
        },
    )
    user_before = crud.get_user_by_email(db_session, "preexisting@example.com")
    assert user_before.google_id is None

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google_token_xyz"}

    mock_profile_resp = MagicMock()
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = {
        "sub": "google_sub_999999",
        "email": "preexisting@example.com",
        "name": "Pre Existing",
        "picture": "https://lh3.googleusercontent.com/a/new_pic.jpg",
    }

    mock_async_client = MagicMock()
    mock_async_client.post = AsyncMock(return_value=mock_token_resp)
    mock_async_client.get = AsyncMock(return_value=mock_profile_resp)
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        resp = client.get(
            "/auth/google/callback?code=code_abc&state=valid_state",
            cookies={"oauth_state": "valid_state"},
            follow_redirects=False,
        )

    assert resp.status_code == 200
    db_session.refresh(user_before)
    assert user_before.google_id == "google_sub_999999"
    assert user_before.profile_picture == "https://lh3.googleusercontent.com/a/new_pic.jpg"
    assert user_before.last_login is not None


def test_google_demo_login(client, db_session):
    """Test demo endpoint provisions demo user and renders success bridge."""
    resp = client.get("/auth/google/demo")
    assert resp.status_code == 200
    assert "AUTHENTICATION SUCCESSFUL" in resp.text
    user = crud.get_user_by_email(db_session, "google.evaluator@example.com")
    assert user is not None
    assert user.google_id == "google_demo_eval_83749281729"
    assert user.role == "HR/User"

