#!/usr/bin/env python3
"""Render namespace/workload TSV for contract-backed Kubernetes Deployments."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DOCUMENT_SEPARATOR = re.compile(r"(?m)^---\s*$")
DEPLOYMENT_KIND = re.compile(r"(?m)^kind:\s*Deployment\s*$")


class IndexError(ValueError):
    pass


def expected_workloads(contract_path: Path) -> set[str]:
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndexError(f"cannot read role contract: {contract_path}") from exc
    workloads = {
        str(row["workload"])
        for row in contract.get("workloads", [])
        if row.get("workload") != "keda-postgres"
    }
    if not workloads:
        raise IndexError("role contract declares no application database workloads")
    return workloads


def metadata_fields(document: str) -> dict[str, str]:
    lines = document.splitlines()
    metadata_start = next((i for i, line in enumerate(lines) if line.strip() == "metadata:" and not line.startswith(" ")), None)
    if metadata_start is None:
        return {}
    fields: dict[str, str] = {}
    for line in lines[metadata_start + 1 :]:
        if not line.strip():
            continue
        if not line.startswith("  "):
            break
        # Only direct metadata children; nested annotations/labels are deeper.
        if line.startswith("    "):
            continue
        match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*([^\s#]+)", line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def build_index(contract_path: Path, manifests: list[Path]) -> list[tuple[str, str]]:
    expected = expected_workloads(contract_path)
    found: dict[str, str] = {}
    for manifest in manifests:
        try:
            text = manifest.read_text(encoding="utf-8")
        except OSError as exc:
            raise IndexError(f"cannot read manifest: {manifest}") from exc
        for document in DOCUMENT_SEPARATOR.split(text):
            if not DEPLOYMENT_KIND.search(document):
                continue
            metadata = metadata_fields(document)
            name = metadata.get("name")
            if name not in expected:
                continue
            namespace = metadata.get("namespace")
            if not namespace or name in found:
                raise IndexError(f"invalid/duplicate database Deployment mapping: {name}")
            found[name] = namespace
    missing = expected - set(found)
    if missing:
        raise IndexError(f"missing database Deployment mappings: {sorted(missing)}")
    return [(found[workload], workload) for workload in sorted(found)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index MReader database workload Deployments by namespace")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--manifest", action="append", required=True, type=Path, dest="manifests")
    args = parser.parse_args(argv)
    try:
        rows = build_index(args.contract, args.manifests)
    except IndexError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for namespace, workload in rows:
        print(f"{namespace}\t{workload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
