#!/usr/bin/env python3
"""Render temporary Kubernetes Deployment manifests bound to a P09.4 generation token."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOKEN = re.compile(r"^p094-[0-9a-f]{64}$")
DEPLOYMENT = re.compile(r"(?m)^kind:\s*Deployment\s*$")
METADATA_NAME = re.compile(r"(?m)^metadata:\s*$\n(?:(?:  [^\n]*)\n)*?  name:\s*([^\s#]+)")
DOCUMENT_SEPARATOR = re.compile(r"(?m)^---\s*\n")
GENERATION_KEY = "MREADER_DEPLOYMENT_GENERATION"


class RenderError(ValueError):
    pass


def deployment_name(document: str) -> str | None:
    if not DEPLOYMENT.search(document):
        return None
    match = METADATA_NAME.search(document)
    if not match:
        raise RenderError("Deployment is missing metadata.name")
    return match.group(1)


def _container_bounds(lines: list[str]) -> tuple[int, int]:
    try:
        containers = next(i for i, line in enumerate(lines) if line == "      containers:")
    except StopIteration as exc:
        raise RenderError("Deployment pod template is missing containers") from exc
    end = len(lines)
    for i in range(containers + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < 6 or (indent == 6 and not line.startswith("      - ")):
            end = i
            break
    return containers + 1, end


def _stamp_container(lines: list[str], start: int, end: int, generation: str) -> None:
    env_line = next((i for i in range(start, end) if lines[i] == "        env:"), None)
    if env_line is None:
        lines[end:end] = ["        env:", f"        - name: {GENERATION_KEY}", f"          value: {generation}"]
        return

    env_end = end
    for i in range(env_line + 1, end):
        if re.match(r"^        [A-Za-z_][A-Za-z0-9_.-]*:\s*", lines[i]):
            env_end = i
            break
    matches = [i for i in range(env_line + 1, env_end) if lines[i] == f"        - name: {GENERATION_KEY}"]
    if len(matches) > 1:
        raise RenderError(f"container has duplicate {GENERATION_KEY} entries")
    if not matches:
        lines[env_end:env_end] = [f"        - name: {GENERATION_KEY}", f"          value: {generation}"]
        return

    item = matches[0]
    item_end = env_end
    for i in range(item + 1, env_end):
        if lines[i].startswith("        - "):
            item_end = i
            break
    value_line = next((i for i in range(item + 1, item_end) if lines[i].startswith("          value:")), None)
    if value_line is None:
        lines[item + 1:item + 1] = [f"          value: {generation}"]
    else:
        lines[value_line] = f"          value: {generation}"


def stamp_document(document: str, generation: str, expected_db_workloads: set[str]) -> tuple[str, str | None]:
    """Return rendered document and matched Deployment name, if any."""
    name = deployment_name(document)
    if name is None or name not in expected_db_workloads:
        return document, None
    trailing_newline = document.endswith("\n")
    lines = document.splitlines()
    start, end = _container_bounds(lines)
    container_starts = [i for i in range(start, end) if re.match(r"^      - name:\s*\S+", lines[i])]
    if not container_starts:
        raise RenderError(f"Deployment {name} has no application containers")
    bounds = [(item, container_starts[index + 1] if index + 1 < len(container_starts) else end) for index, item in enumerate(container_starts)]
    for item_start, item_end in reversed(bounds):
        _stamp_container(lines, item_start, item_end, generation)
    rendered = "\n".join(lines)
    if trailing_newline:
        rendered += "\n"
    return rendered, name


def expected_workloads(contract_path: Path) -> set[str]:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot read role contract: {contract_path}") from exc
    if contract.get("contract") != "mreader.postgres-roles" or contract.get("version") != 1:
        raise RenderError("unsupported role contract/version")
    workloads = {str(row["workload"]) for row in contract.get("workloads", []) if row.get("workload") != "keda-postgres"}
    if not workloads:
        raise RenderError("role contract declares no application database workloads")
    return workloads


def render_files(*, contract_path: Path, generation: str, inputs: list[Path], output_dir: Path) -> None:
    if not TOKEN.fullmatch(generation):
        raise RenderError("generation must match p094-<64 lowercase hex>")
    expected = expected_workloads(contract_path)
    counts = {name: 0 for name in expected}
    rendered_files: list[tuple[str, str]] = []
    output_names: set[str] = set()
    for source in inputs:
        if source.name in output_names:
            raise RenderError(f"duplicate output basename: {source.name}")
        output_names.add(source.name)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise RenderError(f"cannot read manifest: {source}") from exc
        rendered_documents: list[str] = []
        for document in DOCUMENT_SEPARATOR.split(text):
            rendered, matched = stamp_document(document, generation, expected)
            rendered_documents.append(rendered)
            if matched is not None:
                counts[matched] += 1
        rendered_files.append((source.name, "---\n".join(rendered_documents)))
    bad = {name: count for name, count in counts.items() if count != 1}
    if bad:
        raise RenderError(f"expected exactly one Deployment for each database workload: {bad}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rendered_files:
        (output_dir / name).write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stamp MReader hybrid workload templates with a P09.4 generation token")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--input", action="append", required=True, type=Path, dest="inputs")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        render_files(contract_path=args.contract, generation=args.generation, inputs=args.inputs, output_dir=args.output_dir)
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
