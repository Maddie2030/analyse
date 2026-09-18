#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"
APP = FRONTEND / "App.tsx"

ROUTE_RE = re.compile(r'<Route\s+path="([^"]+)"\s+element=\{(.+?)\}\s*/>', re.S)
TAG_RE = re.compile(r'<(?P<tag>button|Link|NavLink|RRNavLink|a)\b(?P<attrs>[^>]*)>', re.S)
ONCLICK_RE = re.compile(r'<(?P<tag>[A-Za-z][A-Za-z0-9.]*)\b(?P<attrs>[^>]*)\bonClick\s*=\s*\{[^>]*>', re.S)
ATTR_RE = re.compile(r'(?P<name>aria-label|title|to|href|type|placeholder)\s*=\s*(?:"(?P<dq>[^"]*)"|\{`(?P<tpl>[^`]*)`\}|\{(?P<expr>[^}]*)\})', re.S)
PLAIN_TEXT_RE = re.compile(r'^\s*([^<{][^<]{0,100}?)\s*<', re.S)


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _attrs(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in ATTR_RE.finditer(raw):
        value = match.group("dq") or match.group("tpl") or match.group("expr") or ""
        result[match.group("name")] = " ".join(value.split())[:180]
    return result


def _label(text: str, end: int, attrs: dict[str, str]) -> str:
    for key in ("aria-label", "title"):
        if attrs.get(key):
            return attrs[key]
    snippet = text[end : end + 220]
    plain = PLAIN_TEXT_RE.search(snippet)
    if plain:
        return " ".join(plain.group(1).split())[:160]
    return ""


def discover_routes() -> list[dict[str, str | int]]:
    text = APP.read_text(encoding="utf-8")
    rows = []
    for match in ROUTE_RE.finditer(text):
        element = " ".join(match.group(2).split())
        rows.append({"path": match.group(1), "element": element[:240], "line": _line(text, match.start())})
    return rows


def discover_controls() -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    seen: set[tuple[str, int, str]] = set()
    roots = [FRONTEND / "pages", FRONTEND / "components"]
    for root in roots:
        for path in sorted(root.glob("*.tsx")):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT).as_posix()
            for regex, kind in ((TAG_RE, "interactive-tag"), (ONCLICK_RE, "onclick-access-point")):
                for match in regex.finditer(text):
                    line = _line(text, match.start())
                    tag = match.group("tag")
                    key = (rel, line, tag)
                    if key in seen:
                        continue
                    seen.add(key)
                    attrs = _attrs(match.group("attrs"))
                    rows.append({
                        "source": rel,
                        "line": line,
                        "kind": kind,
                        "tag": tag,
                        "label": _label(text, match.end(), attrs),
                        "target": attrs.get("to") or attrs.get("href") or "",
                        "type": attrs.get("type", ""),
                    })
    return sorted(rows, key=lambda row: (str(row["source"]), int(row["line"]), str(row["tag"])))


def write_tsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory all React routes and clickable UI access points.")
    parser.add_argument("--out-dir", default="test-results/ui-access-audit")
    args = parser.parse_args()
    out = Path(args.out_dir)
    if not out.is_absolute():
        out = ROOT / out
    routes = discover_routes()
    controls = discover_controls()
    unlabeled = [row for row in controls if row["tag"] == "button" and not row["label"]]
    write_tsv(out / "routes.tsv", routes, ["path", "element", "line"])
    write_tsv(out / "access-points.tsv", controls, ["source", "line", "kind", "tag", "label", "target", "type"])
    summary = {
        "routes": len(routes),
        "access_points": len(controls),
        "button_access_points": sum(row["tag"] == "button" for row in controls),
        "link_access_points": sum(row["tag"] in {"Link", "NavLink", "RRNavLink", "a"} for row in controls),
        "onclick_access_points": sum(row["kind"] == "onclick-access-point" for row in controls),
        "unlabeled_buttons": len(unlabeled),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        "UI access-point audit PASS: "
        f"{summary['routes']} routes, {summary['access_points']} clickable access points inventoried "
        f"({summary['unlabeled_buttons']} source-level unlabeled button candidates)"
    )
    return 0 if routes and controls else 2


if __name__ == "__main__":
    raise SystemExit(main())
