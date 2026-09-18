# Ripwire workflow for MReader

## Purpose

Ripwire is used as a deterministic code-context companion to Superpowers. Superpowers controls *how work is executed* (plan, TDD, debugging, verification); Ripwire controls *how the repository is mapped before and after a change* (orientation, callers/impact, affected tests, quality delta, merge safety, handoff).

Upstream: `redhat-et/ripwire` (Apache-2.0). The workflow was reviewed against upstream v0.6.1 documentation on 2026-09-15.

## Routing

Use these task moments, matching Ripwire's upstream skills:

| Moment | Ripwire action |
| --- | --- |
| Resume/cold orientation | `--recall`, `--situ`, then `--pack-task` |
| Plan a multi-symbol feature | `--pack-task`, then `--seams`/`--impact` if needed |
| Debug a symptom | `--for`, or `--from-trace` when a trace exists |
| Change a known symbol | `--impact`, `--callers`, `--affected` |
| Review our own diff | `--quality-delta`, `--pr-context`, `--test-gate` |
| Merge several branches | `--merge-scout` / `--stray-content --plan` |
| Handoff | `--handoff` plus the tracker checkpoint |

The first choice for MReader multi-file work is:

```bash
ripwire . --pack-task="<task>" --legend=compact
```

Before completion, prefer:

```bash
ripwire . --quality-delta --legend=compact
ripwire . --pr-context --legend=compact
ripwire . --test-gate --legend=compact
```

These are evidence generators, not substitutes for actually running the tests named by the repository or tracker.

## MReader-specific rules

1. Run from the canonical sequential repository recorded in the tracker.
2. Never use a scratch/reference checkout as the implementation root.
3. Use Ripwire output to narrow reads; source and runtime behavior remain authoritative.
4. A Ripwire zero/floor is not proof of global absence when the tool reports skipped/ambiguous content.
5. Do not commit Ripwire caches. Commit `.ripwire_notes` only when a note is a durable project invariant and is reviewed as normal source documentation.
6. Ripwire cannot close a runtime acceptance gate. P06.3 still requires its real PostgreSQL transaction run.
7. When Ripwire is unavailable, record `Ripwire: blocked (executable unavailable)` and continue with equivalent direct source/test inspection rather than fabricating tool output.

## Installation state in this ChatGPT sandbox

The upstream v0.6.1 Linux x64 release exists and publishes SHA-256 digests. The current sandbox's shell cannot resolve/access GitHub release downloads, so the binary is **not installed in this runtime**. This is an environment limitation, not a project decision.

The official user-local installation, when network access is available, is:

```bash
RIPWIRE_REPO=redhat-et/ripwire bash -c "$(curl -fsSL https://raw.githubusercontent.com/redhat-et/ripwire/main/scripts/install.sh)"
export PATH="$HOME/.local/bin:$PATH"
ripwire --version
ripwire . --doctor --legend=compact
```

For isolation, MReader may instead set `RIPWIRE_INSTALL_PREFIX` to a dedicated user-local/tooling directory. Do not use sudo.


## Availability

The canonical sequential workspace has a verified local Ripwire 0.6.1 source build at `../../tools/ripwire/bin/ripwire`. The checked-in wrapper discovers this automatically, after `MREADER_RIPWIRE_BIN` and `PATH`. The full upstream skill set is staged under `../../tools/ripwire/share/ripwire/skills` and 16 MReader-relevant skills are activated under `../../tools/agent-skills`; the Ripwire-contributor-only optimization-remarks skill is intentionally omitted.

Installation provenance lives outside the application source at `../../tools/ripwire/INSTALLATION.md`. The local install is tooling only; it is not part of the MReader release package or runtime.
