from pathlib import Path
from typing import Iterable
import unittest


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require_all(case: unittest.TestCase, source: str, needles: Iterable[str]) -> None:
    for needle in needles:
        case.assertIn(needle, source)


def forbid_all(case: unittest.TestCase, source: str, needles: Iterable[str]) -> None:
    for needle in needles:
        case.assertNotIn(needle, source)
