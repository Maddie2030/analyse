#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

CANONICAL_TARGET = 800
# The canonical ledger is deliberately balanced.  A full API run can produce
# more than 800 parametrized cases by itself; without reserves the requested
# user-perspective ledger would omit browser, gateway and least-privilege
# evidence even though those layers executed.  Shortfalls are redistributed
# from any layer with spare cases, so the ledger still reaches exactly 800 when
# the full qualification run produced at least 800 records.
LAYER_RESERVES = {
    "api": 500,
    "external": 40,
    "browser": 40,
    "boundary": 120,
    "permissions": 100,
}


def load_json(path: Path, default: Any = None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def pytest_records(path: Path, layer: str) -> list[dict[str, Any]]:
    payload = load_json(path, {}) or {}
    result = []
    for row in payload.get("tests", []) or []:
        result.append({
            "layer": layer,
            "id": row.get("nodeid", ""),
            "outcome": row.get("outcome", "unknown"),
            "duration_seconds": row.get("duration_seconds", 0),
            "evidence": str(path),
        })
    return result


def browser_records(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, {}) or {}
    result = []
    for suite in payload.get("suites", []) or []:
        file = suite.get("file") or suite.get("title") or "browser"
        for spec in suite.get("specs", []) or []:
            tests = spec.get("tests", []) or []
            status = "unknown"
            duration = 0.0
            if tests:
                test = tests[-1]
                status = "passed" if test.get("status") == "expected" and spec.get("ok") else "failed"
                outcomes = test.get("results", []) or []
                if outcomes:
                    raw = outcomes[-1].get("status", "")
                    if raw == "skipped":
                        status = "skipped"
                    duration = float(outcomes[-1].get("duration", 0)) / 1000.0
            result.append({
                "layer": "browser",
                "id": f"{file}::{spec.get('title', '')}",
                "outcome": status,
                "duration_seconds": round(duration, 6),
                "evidence": str(path),
            })
    return result


def load_stage_table(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("diagnostic_dir", type=Path)
    parser.add_argument("--ui-audit-dir", type=Path)
    parser.add_argument("--static-summary", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    d = args.diagnostic_dir.resolve(); out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    records += pytest_records(d / "pytest" / "summary.json", "api")
    records += pytest_records(d / "pytest" / "external" / "summary.json", "external")
    records += browser_records(d / "browser" / "playwright-reader.json")
    records += pytest_records(d / "pytest" / "boundary" / "summary.json", "boundary")
    records += pytest_records(d / "pytest" / "permissions" / "summary.json", "permissions")

    # Build a balanced canonical ledger.  Take each layer's reserve first, then
    # redistribute unused slots from layers that did not produce enough cases.
    # This keeps the ledger representative while the *entire* executed set
    # remains the pass/fail authority.
    priority = {"api": 0, "external": 1, "browser": 2, "boundary": 3, "permissions": 4}
    records = sorted(records, key=lambda row: (priority.get(row["layer"], 99), row["id"]))
    by_layer: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        by_layer.setdefault(row["layer"], []).append(row)

    canonical: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    for layer in ("api", "external", "browser", "boundary", "permissions"):
        reserve = LAYER_RESERVES[layer]
        for row in by_layer.get(layer, [])[:reserve]:
            canonical.append(dict(row))
            selected_keys.add((row["layer"], row["id"]))

    if len(canonical) < CANONICAL_TARGET:
        for row in records:
            key = (row["layer"], row["id"])
            if key in selected_keys:
                continue
            canonical.append(dict(row))
            selected_keys.add(key)
            if len(canonical) == CANONICAL_TARGET:
                break
    canonical = canonical[:CANONICAL_TARGET]
    canonical = sorted(canonical, key=lambda row: (priority.get(row["layer"], 99), row["id"]))
    for index, row in enumerate(canonical, 1):
        row["qualification_id"] = f"MQR-{index:04d}"
    write_tsv(out / "qualification-800.tsv", canonical, ["qualification_id", "layer", "id", "outcome", "duration_seconds", "evidence"])

    counts: dict[str, dict[str, int]] = {}
    for row in records:
        bucket = counts.setdefault(row["layer"], {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "unknown": 0})
        bucket["total"] += 1
        outcome = row["outcome"] if row["outcome"] in bucket else "unknown"
        bucket[outcome] += 1

    ui = load_json((args.ui_audit_dir / "summary.json") if args.ui_audit_dir else Path("/__missing__"), {}) or {}
    diagnostic = load_json(d / "REPORT.json", {}) or {}
    stages = load_stage_table(d / "stages.tsv")
    stage_failures = [row for row in stages if row.get("status") == "FAIL"]
    total = len(records)
    failed = sum(row["outcome"] == "failed" for row in records)
    skipped = sum(row["outcome"] == "skipped" for row in records)
    canonical_failed = sum(row["outcome"] == "failed" for row in canonical)
    canonical_layers: dict[str, int] = {}
    for row in canonical:
        canonical_layers[row["layer"]] = canonical_layers.get(row["layer"], 0) + 1
    enough = len(canonical) == CANONICAL_TARGET
    overall = "PASS" if enough and failed == 0 and not stage_failures and diagnostic.get("overall") != "FAIL" else "FAIL"

    payload = {
        "overall": overall,
        "canonical_target": CANONICAL_TARGET,
        "canonical_cases": len(canonical),
        "canonical_failures": canonical_failed,
        "canonical_layers": canonical_layers,
        "canonical_layer_reserves": LAYER_RESERVES,
        "executed_automated_cases": total,
        "executed_failures": failed,
        "executed_skips": skipped,
        "layers": counts,
        "ui_source_inventory": ui,
        "diagnostic_overall": diagnostic.get("overall", "UNKNOWN"),
        "failed_stages": stage_failures,
    }
    (out / "qualification-summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# MReader user-perspective qualification",
        "",
        f"**Overall: {overall}**",
        "",
        f"Canonical requested ledger: **{len(canonical)}/{CANONICAL_TARGET} cases**",
        f"All executed automated cases: **{total}**",
        f"Failures across full execution: **{failed}**",
        f"Skips across full execution: **{skipped}**",
        "",
        "Canonical layer mix: " + ", ".join(f"{name}={canonical_layers.get(name, 0)}" for name in ("api", "external", "browser", "boundary", "permissions")),
        "",
        "## Executed layers",
        "",
        "| Layer | Total | Passed | Failed | Skipped |",
        "|---|---:|---:|---:|---:|",
    ]
    for layer in ("api", "external", "browser", "boundary", "permissions"):
        c = counts.get(layer, {"total":0,"passed":0,"failed":0,"skipped":0})
        lines.append(f"| {layer} | {c['total']} | {c['passed']} | {c['failed']} | {c['skipped']} |")
    lines += [
        "",
        "## UI access-point inventory",
        "",
        f"React routes inventoried: **{ui.get('routes', 0)}**",
        f"Clickable source access points inventoried: **{ui.get('access_points', 0)}**",
        f"Button access points: **{ui.get('button_access_points', 0)}**",
        f"Link access points: **{ui.get('link_access_points', 0)}**",
        "",
        "The `qualification-800.tsv` ledger prioritizes functional API, external scraper, browser E2E, then gateway and DB-permission evidence. The qualification command still fails if any additional executed case outside the canonical 800 fails.",
    ]
    if stage_failures:
        lines += ["", "## Failed diagnostic stages", ""]
        for row in stage_failures:
            lines.append(f"- `{row.get('name')}` exit {row.get('exit_code')}: `{row.get('log')}`")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
