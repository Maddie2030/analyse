#!/bin/sh
set -eu
component="${1:?component required}"
map_line="$(sh ./scripts/ci/image-map.sh "$component")"
context="${map_line%%|*}"
dockerfile="${map_line#*|}"
dockerfile_dir="$(dirname "$dockerfile")"
dockerfile_name="$(basename "$dockerfile")"
if [ "$context" = frontend ]; then
  dockerfile_dir=frontend
  dockerfile_name=Dockerfile
fi
export BUILDKITD_FLAGS="${BUILDKITD_FLAGS:---oci-worker-no-process-sandbox}"
echo "Build-checking $component"
buildctl-daemonless.sh build \
  --frontend dockerfile.v0 \
  --local context="$context" \
  --local dockerfile="$dockerfile_dir" \
  --opt filename="$dockerfile_name" \
  --output type=cacheonly
