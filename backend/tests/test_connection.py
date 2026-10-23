"""
Unit tests verifying the bidirectional connection between the Home page (index.html)
and the Login page (login.html) and Registration page (register.html).
"""
import pytest


def test_home_page_contains_login_link(client):
    """Home / Dashboard page must have direct link to the login page."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'href="/login"' in html
    assert 'btn-sidebar-login' in html
    assert 'Login Page' in html


def test_login_page_contains_home_link(client):
    """Login page must have direct link returning to the Home / Dashboard."""
    resp = client.get("/login")
    assert resp.status_code == 200
    html = resp.text
    assert 'href="/"' in html
    assert 'Home / Dashboard' in html
    assert 'btn-nav-home' in html


def test_register_page_contains_home_link(client):
    """Registration page must have direct link returning to the Home / Dashboard."""
    resp = client.get("/register")
    assert resp.status_code == 200
    html = resp.text
    assert 'href="/"' in html
    assert 'Home / Dashboard' in html
    assert 'btn-nav-home' in html


def test_login_authenticates_and_grants_access(client):
    """Successful login issues JWT access token for dashboard operations."""
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Test Connector",
            "username": "connector",
            "email": "connector@example.com",
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201

    login_resp = client.post(
        "/auth/login",
        json={"username_or_email": "connector", "password": "Password123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Dashboard session verification
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "connector"
