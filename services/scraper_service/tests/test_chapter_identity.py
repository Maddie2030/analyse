import pytest

from app.chapter_identity import chapter_slug_from_number, normalize_chapter_number


@pytest.mark.parametrize(
    ("raw", "number_text", "slug"),
    [
        ("13", "13", "ch-13"),
        ("13.50", "13.5", "ch-13-5"),
        ("0013.500", "13.5", "ch-13-5"),
        ("0.5", "0.5", "ch-0-5"),
        ("0", "0", "ch-0"),
    ],
)
def test_chapter_identity_is_derived_only_from_number(raw, number_text, slug):
    _number, text = normalize_chapter_number(raw)
    assert text == number_text
    assert chapter_slug_from_number(raw) == slug


@pytest.mark.parametrize("raw", ["", "chapter-13", "nan", "Infinity", "-1"])
def test_invalid_chapter_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_chapter_number(raw)
