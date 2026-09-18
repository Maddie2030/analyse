#!/bin/sh
set -eu
component="${1:?component required}"
registry="${MREADER_REGISTRY:?MREADER_REGISTRY required}"
tag="${IMAGE_TAG:?IMAGE_TAG required}"
map_line="$(sh ./scripts/ci/image-map.sh "$component")"
context="${map_line%%|*}"
dockerfile="${map_line#*|}"
ref="${registry%/}/${component}:${tag}"
metadata="${BUILD_METADATA_DIR:-.ci-artifacts}/metadata-${component}.json"
mkdir -p "$(dirname "$metadata")"
dockerfile_dir="$(dirname "$dockerfile")"
dockerfile_name="$(basename "$dockerfile")"
if [ "$context" = frontend ]; then
  dockerfile_dir=frontend
  dockerfile_name=Dockerfile
fi
export BUILDKITD_FLAGS="${BUILDKITD_FLAGS:---oci-worker-no-process-sandbox}"
buildctl-daemonless.sh build \
  --frontend dockerfile.v0 \
  --local context="$context" \
  --local dockerfile="$dockerfile_dir" \
  --opt filename="$dockerfile_name" \
  --opt build-arg:BUILDKIT_INLINE_CACHE=1 \
  --output "type=image,name=$ref,push=true" \
  --metadata-file "$metadata"
digest="$(grep -o '"containerimage.digest"[[:space:]]*:[[:space:]]*"sha256:[^"]*"' "$metadata" | head -1 | sed -E 's/.*"(sha256:[^"]+)"/\1/')"
case "$digest" in sha256:*) ;; *) echo "missing digest for $component" >&2; cat "$metadata" >&2; exit 1;; esac
printf '%s=%s@%s\n' "$component" "${registry%/}/${component}" "$digest" | tee -a "${BUILD_METADATA_DIR:-.ci-artifacts}/images.env"
