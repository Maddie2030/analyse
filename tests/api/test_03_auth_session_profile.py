from helpers import assert_status


def test_login_rejects_wrong_password(temp_user_factory):
    user = temp_user_factory("loginbad")
    user.session.post("/api/auth/logout", timeout=10)

    response = user.session.post(
        "/api/auth/login",
        json={
            "username_or_email": user.username,
            "password": "definitely-wrong",
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(response, 401)


def test_login_profile_logout_flow(temp_user_factory):
    user = temp_user_factory("profile")
    user.session.post("/api/auth/logout", timeout=10)

    login = user.session.post(
        "/api/auth/login",
        json={
            "username_or_email": user.email,
            "password": user.password,
            "turnstile_token": "",
        },
        timeout=10,
    )
    assert_status(login, 200)

    profile = user.session.get("/api/auth/profile", timeout=10)
    assert_status(profile, 200)
    assert profile.json()["id"] == user.user_id

    logout = user.session.post("/api/auth/logout", timeout=10)
    assert_status(logout, 200)

    after = user.session.get("/api/auth/profile", timeout=10)
    assert_status(after, 401)



def test_profile_account_identifiers_are_locked(temp_user_factory):
    user = temp_user_factory("lockedids")

    before = user.session.get("/api/auth/profile", timeout=10)
    assert_status(before, 200)
    original = before.json()

    username = user.session.put(
        "/api/auth/profile",
        json={"username": "attempted_username_change"},
        timeout=10,
    )
    assert_status(username, 409)
    assert "locked account identifier" in username.text.lower()

    email = user.session.put(
        "/api/auth/profile",
        json={"email": "attempted-change@gmail.com"},
        timeout=10,
    )
    assert_status(email, 409)
    assert "locked account identifier" in email.text.lower()

    after = user.session.get("/api/auth/profile", timeout=10)
    assert_status(after, 200)
    assert after.json()["username"] == original["username"]
    assert after.json()["email"] == original["email"]

def test_profile_avatar_selection_is_fixed_and_persisted(temp_user_factory):
    user = temp_user_factory("avatar")

    before = user.session.get("/api/auth/profile", timeout=10)
    assert_status(before, 200)
    assert before.json()["avatar_key"] == "skull"

    replacement_avatars = [
        "bard", "cleric", "fire_wielder", "king", "paladin",
        "shadow_rogue", "sorcerer", "swordsman",
    ]
    for avatar_key in replacement_avatars:
        changed = user.session.put(
            "/api/auth/profile",
            json={"avatar_key": avatar_key},
            timeout=10,
        )
        assert_status(changed, 200)
        assert changed.json()["avatar_key"] == avatar_key

    after = user.session.get("/api/auth/profile", timeout=10)
    assert_status(after, 200)
    assert after.json()["avatar_key"] == replacement_avatars[-1]

    invalid = user.session.put(
        "/api/auth/profile",
        json={"avatar_key": "https://example.invalid/avatar.png"},
        timeout=10,
    )
    assert_status(invalid, 422)

def test_admin_stats_requires_admin(admin_regular_user, admin_user):
    regular = admin_regular_user.session.get("/api/auth/admin/stats", timeout=10)
    assert_status(regular, 403)

    admin = admin_user.session.get("/api/auth/admin/stats", timeout=10)
    assert_status(admin, 200)
    assert admin.json()["user_count"] >= 2
