#!/usr/bin/env bash
set -euo pipefail

spec="tests/browser/reading-consistency.spec.mjs"
[[ -f "$spec" ]] || { echo "FAIL: missing P03.2 browser reading acceptance spec: $spec" >&2; exit 1; }

require() {
  local pattern="$1" message="$2"
  grep -Eq "$pattern" "$spec" || { echo "FAIL: $message" >&2; exit 1; }
}

require "test\\('two tabs preserve" "two-tab reading concurrency scenario missing"
require "test\\('quota failure keeps" "quota-failure reading scenario missing"
require "test\\('offline refresh preserves" "offline refresh reading scenario missing"
require "test\\('late acknowledgement cannot" "late-acknowledgement reading scenario missing"
require "test\\('media failure does not" "media-failure reading scenario missing"
require "test\\('reader IndexedDB checkpoint reaches server progress and Smart Library UI" "IndexedDB-to-Smart-Library browser chain missing"
require 'reading_progress' "browser chain must verify canonical PostgreSQL reading_progress state"
require '/api/social/library\?scope=history' "browser chain must verify Smart Library history projection"
require "getByRole\\('button', \\{ name: 'History' \\}\\)" "browser chain must verify Smart Library History UI"
require 'context\.newPage\(' "two-tab scenario must use a shared browser context"
require 'indexedDB|IDBObjectStore' "quota scenario must exercise browser IndexedDB failure behavior"
require 'setOffline\(true\)|setOffline\(false\)' "offline scenario must explicitly toggle browser network state"
require 'route\(.*/api/progress|route\(.*/progress' "late ACK scenario must control a real Progress request"
require '/images/' "media failure scenario must intercept reader media"
require 'data-page-index' "spec must exercise the real Reader page surface"

node --check "$spec" >/dev/null
printf '%s\n' 'P03.2 browser reading acceptance source contract PASSED'
