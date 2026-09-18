from __future__ import annotations

from decimal import Decimal, InvalidOperation


def normalize_chapter_number(value: str | int | float | Decimal) -> tuple[Decimal, str]:
    """Return a finite, non-negative chapter number and its canonical decimal text."""
    raw = str(value).strip()
    if not raw:
        raise ValueError("Invalid chapter number.")

    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid chapter number.") from None

    if not number.is_finite() or number < 0:
        raise ValueError("Invalid chapter number.")

    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    return number, text


def chapter_slug_from_number(value: str | int | float | Decimal) -> str:
    """Create the only canonical scraper chapter slug from its chapter number."""
    _number, text = normalize_chapter_number(value)
    return f"ch-{text.replace('.', '-')}"
