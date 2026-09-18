#!/bin/sh
set -eu
APP_UID="${MREADER_APP_UID:-10001}"
APP_GID="${MREADER_APP_GID:-10001}"
STAGING_ROOT="${SCRAPER_STAGING_ROOT:-/var/lib/mreader/scraper-staging}"
mkdir -p "$STAGING_ROOT"
marker="$STAGING_ROOT/.mreader-staging-spool-id"
root_owner="$(stat -c '%u:%g' "$STAGING_ROOT" 2>/dev/null || true)"
marker_owner=""
if [ -e "$marker" ]; then marker_owner="$(stat -c '%u:%g' "$marker" 2>/dev/null || true)"; fi
if [ "$root_owner" != "$APP_UID:$APP_GID" ] || { [ -n "$marker_owner" ] && [ "$marker_owner" != "$APP_UID:$APP_GID" ]; }; then
    echo "Repairing scraper staging ownership ${root_owner:-unknown} -> $APP_UID:$APP_GID"
    chown -R "$APP_UID:$APP_GID" "$STAGING_ROOT"
else
    chown "$APP_UID:$APP_GID" "$STAGING_ROOT"
fi
chmod 0770 "$STAGING_ROOT"
if [ -e "$marker" ]; then
    chown "$APP_UID:$APP_GID" "$marker" || true
    chmod 0660 "$marker" || true
fi
find "$STAGING_ROOT" -maxdepth 1 -type f -name '.write-probe-*' -delete 2>/dev/null || true
sync || true
echo "Scraper staging volume permissions ready: root=$STAGING_ROOT owner=$(stat -c '%u:%g' "$STAGING_ROOT") mode=$(stat -c '%a' "$STAGING_ROOT")"
