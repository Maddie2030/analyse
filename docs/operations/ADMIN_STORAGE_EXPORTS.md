# Admin chapter storage exports — RC12

Admin UI: `/admin/storage`.

## Stored ZIP

Downloads the exact page objects currently persisted in SeaweedFS plus a private manifest.

- v0: normal stored image.
- v2: legacy scrambled WebP.
- v3: lossless padded-grid scrambled WebP.
- v4: `.mrt` overlap tile-pack.
- if a page has a persisted responsive derivative, that derivative is included as a separate stored variant and recorded in the manifest.

This is the preferred byte-exact backup format.

## Decoded ZIP

Downloads readable recovery/export images. Protected versions are reconstructed server-side. When a responsive derivative is persisted, the export records/exports it as a distinct variant rather than silently dropping storage state.

Decoded export uses temporary server CPU/disk and is for administration/recovery, not reader delivery.

## Why not copy the Docker `seaweed_volume` directly?

SeaweedFS volume-server data is an internal volume format, not a normal chapter directory tree. Export through the Filer API so logical paths work regardless of which physical volume owns each object.

## API

```text
GET /api/upload/admin/chapters/{chapter_id}/download?mode=stored
GET /api/upload/admin/chapters/{chapter_id}/download?mode=decoded
```

Both require an authenticated admin session and return private/no-store responses.

## Backup security

Stored manifests contain codec metadata needed for recovery. Treat the archives as private administrative backups.
