#!/bin/sh
set -eu

APP_UID="${MREADER_APP_UID:-10001}"
APP_GID="${MREADER_APP_GID:-10001}"
STAGING_ROOT="${SCRAPER_STAGING_ROOT:-/var/lib/mreader/scraper-staging}"

repair_staging_permissions() {
    mkdir -p "$STAGING_ROOT"
    marker="$STAGING_ROOT/.mreader-staging-spool-id"

    root_owner="$(stat -c '%u:%g' "$STAGING_ROOT" 2>/dev/null || true)"
    marker_owner=""
    if [ -e "$marker" ]; then
        marker_owner="$(stat -c '%u:%g' "$marker" 2>/dev/null || true)"
    fi

    # If the volume root or control marker drifted to another uid/gid, nested
    # staged data may have drifted too. Repair recursively once in that abnormal
    # case; healthy starts touch only the root/marker and stay O(1).
    if [ "$root_owner" != "$APP_UID:$APP_GID" ] || { [ -n "$marker_owner" ] && [ "$marker_owner" != "$APP_UID:$APP_GID" ]; }; then
        chown -R "$APP_UID:$APP_GID" "$STAGING_ROOT"
    else
        chown "$APP_UID:$APP_GID" "$STAGING_ROOT"
        if [ -e "$marker" ]; then
            chown "$APP_UID:$APP_GID" "$marker" || true
        fi
    fi

    chmod 0770 "$STAGING_ROOT"
    if [ -e "$marker" ]; then
        chmod 0660 "$marker" || true
    fi
    find "$STAGING_ROOT" -maxdepth 1 -type f -name '.write-probe-*' -delete 2>/dev/null || true
}

# Docker named volumes can retain root ownership/modes from an older container,
# migration helper, restore, or Docker Desktop volume recreation. Every process
# that consumes the spool repairs it before immediately dropping privileges.
if [ "$(id -u)" = "0" ]; then
    repair_staging_permissions
    exec gosu "$APP_UID:$APP_GID" "$@"
fi

exec "$@"
