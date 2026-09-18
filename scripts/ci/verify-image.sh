#!/bin/sh
set -eu
component="${1:?component required}"
entry="$(grep -E "^${component}=" "${BUILD_METADATA_DIR:-.ci-artifacts}/images.env" | tail -1 | cut -d= -f2-)"
case "$entry" in *@sha256:*) ;; *) echo "digest not found for $component" >&2; exit 1;; esac
echo "Scanning $entry"
trivy image --exit-code 1 --severity CRITICAL --ignore-unfixed "$entry"
mkdir -p "${BUILD_METADATA_DIR:-.ci-artifacts}/sbom"
trivy image --format cyclonedx --output "${BUILD_METADATA_DIR:-.ci-artifacts}/sbom/${component}.cdx.json" "$entry"
if [ -x "${WORKSPACE:-.}/.ci-tools/cosign" ]; then
  COSIGN_PASSWORD="${COSIGN_PASSWORD:-}" "${WORKSPACE:-.}/.ci-tools/cosign" sign --yes --key /secrets/cosign/cosign.key "$entry"
else
  echo "cosign binary missing" >&2
  exit 1
fi
