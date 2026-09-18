#!/usr/bin/env bash
set -euo pipefail
env_name="${1:?environment required}"
values_file="${2:-.ci-artifacts/built-values.yaml}"
: "${MREADER_GITOPS_URL:?}" "${GIT_USERNAME:?}" "${GIT_TOKEN:?}"
branch="${MREADER_GITOPS_BRANCH:-main}"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
url="$MREADER_GITOPS_URL"
if [[ "$url" == https://* ]]; then url="https://${GIT_USERNAME}:${GIT_TOKEN}@${url#https://}"; fi
git clone --depth 1 --branch "$branch" "$url" "$work/repo"
mkdir -p "$work/repo/environments"
cp "$values_file" "$work/repo/environments/${env_name}-images.yaml"
cd "$work/repo"
git config user.name mreader-jenkins
git config user.email mreader-ci@localhost
git add "environments/${env_name}-images.yaml"
if git diff --cached --quiet; then echo 'GitOps image state unchanged'; exit 0; fi
git commit -m "deploy(${env_name}): ${GIT_COMMIT:-unknown}"
git push origin "$branch"
