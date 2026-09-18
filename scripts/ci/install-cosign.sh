#!/usr/bin/env sh
set -eu
readonly version="3.1.3"
out="${WORKSPACE:-.}/.ci-tools/cosign"
mkdir -p "$(dirname "$out")"
arch="$(uname -m)"; case "$arch" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) echo "unsupported arch $arch" >&2; exit 1;; esac
curl -fsSL "https://github.com/sigstore/cosign/releases/download/v${version}/cosign-linux-${arch}" -o "$out"
chmod 0755 "$out"
"$out" version
