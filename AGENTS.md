# MReader agent workflow

This repository's canonical task authority is:

`docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md`

Detailed continuation map: `docs/continuation/RC485-CONTINUATION-MANIFEST.md`. Run `scripts/diagnostics/continuation-status.sh` before editing in a fresh session.

## Required workflow

Use **Superpowers** for process discipline: executing the written plan, systematic debugging, test-driven development, isolated changes, and verification before completion.

Use **Ripwire** for repository context whenever the executable is available. Ripwire is a read-first companion, not a replacement for tests or the tracker.

Before a multi-symbol implementation or architectural change:

```bash
scripts/diagnostics/ripwire-context.sh pack "<task in plain words>"
```

Before editing a known symbol or boundary, inspect its impact/callers with the wrapper's `impact` mode. For a bug, use `bug`. Before claiming a change is ready, use `change-check`. At a handoff, use `handoff`.

If Ripwire is unavailable, the wrapper must report that fact. Do not invent or paraphrase Ripwire results. Continue using the tracker plus direct source/test evidence and record Ripwire as blocked for that checkpoint.

Never let Ripwire notes, caches, generated reports, or a reference checkout become an alternate source-of-truth repository. The canonical sequential repo and tracker above remain authoritative.
