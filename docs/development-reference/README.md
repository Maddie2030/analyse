# MReader development reference tooling

This directory contains stable architecture/issue-triage guides used with the package-generated `development-reference/` directory.

Build a checkpoint-specific reference from the repository root:

```bash
./scripts/development-reference/build-reference.sh --out development-reference
```

The generated directory contains deterministic code/development graphs plus Graphify and Ripwire evidence. Graphify native AST extraction is optional; when Tree-sitter parser dependencies are unavailable, the deterministic builders use source imports, Python AST where possible, route ownership, deployment/config references, storage/event contracts, and explicitly tagged `INFERRED` architecture edges.

Use `ISSUE-TO-CHANGE-INDEX.md` and `scripts/development-reference/mreader-impact.py` to classify an issue, then run Graphify `query`, `explain`, and `affected` before editing.
