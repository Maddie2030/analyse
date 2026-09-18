import uuid

from helpers import assert_status


def test_register_rejects_short_username(anonymous):
    response = anonymous.post(
        "/api/auth/register",
        json={
            "username": "x",
            "email": f"mreader.validation+{uuid.uuid4().hex}@gmail.com",
            "password": "TestPassword123!",
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 422)


def test_register_rejects_short_password(anonymous):
    response = anonymous.post(
        "/api/auth/register",
        json={
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": f"mreader.validation+{uuid.uuid4().hex}@gmail.com",
            "password": "short",
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 422)


def test_register_rejects_invalid_email(anonymous):
    response = anonymous.post(
        "/api/auth/register",
        json={
            "username": f"user_{uuid.uuid4().hex[:8]}",
            "email": "not-an-email",
            "password": "TestPassword123!",
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 422)


def test_duplicate_registration_conflicts(temp_user_factory):
    user = temp_user_factory("dupuser")

    response = user.session.post(
        "/api/auth/register",
        json={
            "username": user.username,
            "email": f"mreader.validation+other_{uuid.uuid4().hex}@gmail.com",
            "password": user.password,
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 409)

    response = user.session.post(
        "/api/auth/register",
        json={
            "username": f"other_{uuid.uuid4().hex[:8]}",
            "email": user.email,
            "password": user.password,
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 409)
