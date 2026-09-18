import re

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,50}$")


def validate_username(value: str) -> str:
    if not _USERNAME_RE.match(value):
        raise ValueError("Username must be 3-50 chars, letters/digits/underscores only.")
    return value


def validate_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    return value
