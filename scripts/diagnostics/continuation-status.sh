#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd "$script_dir/../.." && pwd -P)"
tracker="$repo_root/docs/superpowers/plans/2026-09-15-rc485-sequential-action-plan.md"
manifest="$repo_root/docs/continuation/RC485-CONTINUATION-MANIFEST.md"
completion_gate="$repo_root/docs/qualification/RC485-P06.3-COMPLETION-GATE.md"

cd "$repo_root"

printf 'MReader RC4.85 continuation status\n'
printf 'repo=%s\n' "$repo_root"
printf 'branch=%s\n' "$(git branch --show-current)"
printf 'head=%s\n' "$(git rev-parse HEAD)"
printf 'subject=%s\n' "$(git log -1 --pretty=%s)"
printf 'dirty_files=%s\n' "$(git status --porcelain | wc -l | tr -d ' ')"
printf 'tracker=%s\n' "$tracker"
printf 'manifest=%s\n' "$manifest"
printf 'completion_gate=%s\n' "$completion_gate"
printf '\n[stash]\n'
git stash list || true
printf '\n[remotes]\n'
git remote -v || true
printf '\n[branches]\n'
git branch --format='%(refname:short) %(objectname:short) %(subject)' || true
printf '\n[ripwire]\n'
if "$repo_root/scripts/diagnostics/ripwire-context.sh" doctor; then
  :
else
  rc=$?
  printf 'Ripwire doctor failed/blocked (exit=%s). Do not fabricate Ripwire evidence.\n' "$rc" >&2
fi
printf '\n[current-task]\n'
grep -m1 '^\*\*Current task:' "$tracker" || true
printf '\n[next-action]\n'
printf '%s\n' 'Read tracker + continuation manifest + P06.3 completion gate. Do not apply P06.4 stash until P06.3 is Verified.'
