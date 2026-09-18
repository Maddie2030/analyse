#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fail() { echo "dependency pin regression FAILED: $*" >&2; exit 1; }

# Python runtime/test requirements: every declared package must use ==exact.
while IFS= read -r file; do
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | awk '{$1=$1; print}')"
    [[ -z "$line" ]] && continue
    [[ "$line" == *'=='* ]] || fail "$file contains non-exact dependency: $line"
    [[ "$line" != *'>='* && "$line" != *'<='* && "$line" != *'~='* && "$line" != *'!='* ]] || fail "$file contains a range/operator: $line"
  done < "$file"
done < <(find services tests -type f -name 'requirements*.txt' -print | sort)

# Shared Python package dependencies must also be exact.
if grep -Eq 'install_requires|"[A-Za-z0-9_.-]+(\[[^]]+\])?(>=|<=|~=|!=)|"[A-Za-z0-9_.-]+(\[[^]]+\])?"[[:space:]]*,' shared/setup.py; then
  # The second alternative can catch unversioned entries; verify each install line below.
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*\" ]] || continue
    [[ "$line" == *'=='* ]] || fail "shared/setup.py contains non-exact dependency: $line"
  done < <(sed -n '/install_requires=\[/,/\]/p' shared/setup.py)
fi

# npm manifests: direct dependencies/devDependencies must be literal exact versions.
for file in $(find frontend services tests -type f -name package.json -print | sort); do
  if grep -Eq '"[^"]+"[[:space:]]*:[[:space:]]*"(\^|~|>|<|\*|latest|next|[0-9]+\.x|[0-9]+\.[0-9]+\.x)' "$file"; then
    fail "$file contains a floating npm dependency"
  fi
done

# npm direct dependencies/devDependencies must be literal patch-exact semver
# values. This rejects git URLs, tags, workspace wildcards and other resolvers,
# not only caret/tilde ranges.
semver_re='^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'
while IFS='|' read -r file section name version; do
  [[ -n "$file" ]] || continue
  [[ "$version" =~ $semver_re ]] || fail "$file $section.$name is not exact semver: $version"
done < <(
  for file in $(find frontend services tests -type f -name package.json -print | sort); do
    awk -v file="$file" '
      /^[[:space:]]*"(dependencies|devDependencies|optionalDependencies|peerDependencies)"[[:space:]]*:[[:space:]]*\{/ {
        section=$0; sub(/^[[:space:]]*"/,"",section); sub(/".*/,"",section); indeps=1; next
      }
      indeps && /^[[:space:]]*\}/ {indeps=0; section=""; next}
      indeps && match($0,/^[[:space:]]*"[^"]+"[[:space:]]*:[[:space:]]*"[^"]+"/) {
        line=substr($0,RSTART,RLENGTH)
        name=line; sub(/^[[:space:]]*"/,"",name); sub(/".*/,"",name)
        version=line; sub(/^[^:]+:[[:space:]]*"/,"",version); sub(/".*/,"",version)
        print file "|" section "|" name "|" version
      }
    ' "$file"
  done
)

# Container images must not float via latest or tag interpolation.
while IFS= read -r file; do
  if grep -En '^[[:space:]]*image:[[:space:]]*[^#]*(latest|\$\{)' "$file" >/dev/null; then
    grep -En '^[[:space:]]*image:[[:space:]]*[^#]*(latest|\$\{)' "$file" >&2 || true
    fail "$file contains a floating image reference"
  fi
done < <(find . -type f \( -name '*.yml' -o -name '*.yaml' \) -print | sort)

while IFS= read -r file; do
  if grep -En '^FROM[[:space:]]+[^[:space:]]*(latest|\$\{)' "$file" >/dev/null; then
    grep -En '^FROM[[:space:]]+[^[:space:]]*(latest|\$\{)' "$file" >&2 || true
    fail "$file contains a floating base image"
  fi
  # Reject the broad base tags that caused non-reproducible rebuilds previously.
  if grep -En '^FROM[[:space:]]+(python:[0-9]+\.[0-9]+-slim|golang:[0-9]+\.[0-9]+-alpine|node:[0-9]+-(alpine|bookworm-slim)|postgres:[0-9]+-alpine|alpine:[0-9]+\.[0-9]+)$' "$file" >/dev/null; then
    fail "$file contains a patch-floating base image"
  fi
done < <(find . -type f -name 'Dockerfile*' -print | sort)

# Cluster add-ons are immutable code constants, not environment overrides.
grep -Fq 'readonly METRICS_SERVER_VERSION="v0.9.0"' scripts/hybrid/install-autoscaling.sh || fail 'metrics-server version is not exact'
grep -Fq 'readonly KEDA_VERSION="2.20.1"' scripts/hybrid/install-autoscaling.sh || fail 'KEDA version is not exact'
! grep -Eq 'METRICS_SERVER_VERSION="\$\{|KEDA_VERSION="\$\{' scripts/hybrid/install-autoscaling.sh || fail 'autoscaling versions remain overrideable/floating'

# The active public connector image is exact and the actual target is user-only.
grep -Fq 'image: cloudflare/cloudflared:2026.8.3' deploy/compose/docker-compose.hybrid-public-edge.yml || fail 'cloudflared image is not exact'
grep -Fq 'image: chrislusf/seaweedfs:4.41' ops/nas-seaweedfs/docker-compose.yml || fail 'SeaweedFS image is not exact'

# Go language/toolchain directive is patch-exact in every module.
while IFS= read -r file; do
  grep -Eq '^go [0-9]+\.[0-9]+\.[0-9]+$' "$file" || fail "$file does not pin the Go toolchain language version exactly"
done < <(find services -type f -name go.mod -print | sort)

# CI-installed security tooling is exact and not environment-overridable.
grep -Fq 'readonly version="3.1.3"' scripts/ci/install-cosign.sh || fail 'cosign version is not exact'
! grep -Fq 'COSIGN_VERSION:-' scripts/ci/install-cosign.sh || fail 'cosign version remains overrideable'

# Explicit OS packages remain constrained, but Alpine stable repositories roll
# package revisions. Require compatibility floors for apk packages instead of
# exact x.y.z-rN pins that can disappear between rebuilds. Debian/Ubuntu apt
# packages keep the existing exact-version contract.
while IFS= read -r file; do
  awk -v file="$file" '
    function clean(tok){gsub(/^['"']|['"']$/, "", tok); return tok}
    function check_apk(block,   tail,n,a,i,tok){
      tail=substr(block,index(block,"apk add")+7)
      sub(/[[:space:]]+(&&|;|\|\||>)[[:space:]]*.*$/,"",tail)
      n=split(tail,a,/[[:space:]]+/)
      for(i=1;i<=n;i++){
        tok=clean(a[i])
        if(tok==""||tok=="\\"||tok~/^-/)continue
        if(tok !~ />=/){print file ": Alpine package lacks compatibility floor: " tok > "/dev/stderr"; bad=1}
        if(tok ~ /=.*-r[0-9]+$/){print file ": Alpine package exact-pins mutable revision: " tok > "/dev/stderr"; bad=1}
      }
    }
    function check_apt(block,   tail,n,a,i,tok){
      tail=substr(block,index(block,"apt-get install")+15)
      sub(/[[:space:]]+(&&|;|\|\||>)[[:space:]]*.*$/,"",tail)
      n=split(tail,a,/[[:space:]]+/)
      for(i=1;i<=n;i++){
        tok=clean(a[i])
        if(tok==""||tok=="\\"||tok~/^-/)continue
        if(index(tok,"=")==0){print file ": unpinned apt package " tok > "/dev/stderr"; bad=1}
      }
    }
    {
      line=$0
      if(inblock){
        block=block " " line
        if(line!~/\\[[:space:]]*$/){
          if(kind=="apk")check_apk(block); else check_apt(block)
          inblock=0; block=""; kind=""
        }
        next
      }
      if(line~/apk add/){block=line; kind="apk"; if(line~/\\[[:space:]]*$/)inblock=1; else{check_apk(block);block="";kind=""}}
      else if(line~/apt-get install/){block=line; kind="apt"; if(line~/\\[[:space:]]*$/)inblock=1; else{check_apt(block);block="";kind=""}}
    }
    END{
      if(inblock){if(kind=="apk")check_apk(block); else check_apt(block)}
      if(bad)exit 1
    }
  ' "$file" || fail "$file contains an unstable OS package constraint"
done < <(find . -type f -name 'Dockerfile*' -print | sort)

# PostgreSQL backup helper uses compatibility floors on Alpine v3.22 stable; exact -rN pins are intentionally avoided because stable repositories roll revisions.
grep -Fq "'bash>=5.2.37'" ops/postgres-backup/Dockerfile || fail 'postgres backup bash compatibility floor drifted'
grep -Fq "'jq>=1.8.1'" ops/postgres-backup/Dockerfile || fail 'postgres backup jq compatibility floor drifted'
grep -Fq "'coreutils>=9.7'" ops/postgres-backup/Dockerfile || fail 'postgres backup coreutils compatibility floor drifted'
grep -Fq "'tzdata>=2026a'" ops/postgres-backup/Dockerfile || fail 'postgres backup tzdata compatibility floor drifted'
! grep -Eq 'apk add[^\n]*(bash|jq|coreutils|tzdata)=[^~<>]*[0-9]-r[0-9]+' ops/postgres-backup/Dockerfile || fail 'postgres backup must not exact-pin mutable Alpine package revisions'
grep -Fq 'FROM postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297' ops/postgres-backup/Dockerfile || fail 'postgres backup base image is not digest-pinned'
grep -Fq 'FROM postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297' ops/migrate/Dockerfile || fail 'migration base image is not digest-pinned'

# Browser dependencies are pre-baked at the same exact Playwright version;
# do not reintroduce dynamic browser/system dependency downloads.
grep -Fq 'mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:' services/scraper_service/Dockerfile.browser || fail 'browser scraper Playwright image is not exact/digest-pinned'
grep -Fq 'playwright==1.62.0' services/scraper_service/requirements-browser.txt || fail 'browser scraper Python Playwright package does not match image'
! grep -RInE 'playwright[[:space:]]+install(-deps)?' services/scraper_service/Dockerfile.browser >/dev/null || fail 'browser scraper dynamically installs Playwright dependencies'
grep -Fq 'mcr.microsoft.com/playwright:v1.62.0-noble@sha256:' tests/browser/Dockerfile || fail 'browser-test Playwright image is not exact/digest-pinned'
grep -Fq '"@playwright/test": "1.62.0"' tests/browser/package.json || fail 'browser-test Playwright package does not match image'

# Frontend must use the committed lockfile. Other npm packages still require
# exact direct declarations; do not claim transitive lock reproducibility for
# packages without a lockfile.
[[ -f frontend/package-lock.json ]] || fail 'frontend package-lock.json is missing'
grep -Fq 'RUN npm ci --no-audit --no-fund' frontend/Dockerfile || fail 'frontend Dockerfile does not use npm ci'

echo 'dependency pin regression PASSED'

