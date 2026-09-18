import copy
import json
import subprocess
import tempfile
from pathlib import Path


def read_json_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_json_audit(*, root: Path, candidate: Path, command: list[str]):
    return subprocess.run(
        [*command, str(candidate)], cwd=root, text=True, capture_output=True, check=False
    )


def run_mutated_json_audit(*, root: Path, source: Path, command: list[str], mutate):
    data = copy.deepcopy(read_json_file(source))
    mutate(data)
    with tempfile.TemporaryDirectory() as td:
        candidate = Path(td) / source.name
        candidate.write_text(json.dumps(data), encoding="utf-8")
        return run_json_audit(root=root, candidate=candidate, command=command)


def text_marker_mismatches(path: Path, *, required=(), forbidden=()):
    text = path.read_text(encoding="utf-8")
    problems = [f"missing:{marker}" for marker in required if marker not in text]
    problems.extend(f"forbidden:{marker}" for marker in forbidden if marker in text)
    return problems
