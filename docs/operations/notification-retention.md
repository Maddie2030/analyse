# Notification retention

Social TypeScript owns notification retention in the primary runtime.

## Policy

- Read notifications: delete when `created_at` is older than 14 days.
- Unread notifications: delete when `created_at` is older than 30 days.
- The clock is delivery time (`created_at`), not the time the user reads it.
- Default maintenance sweep: every 24 hours.

A notification delivered 20 days ago and read today is already past the read
retention boundary. A notification delivered 20 days ago and still unread is
kept until day 30.

## Operational design

Cleanup runs inside `social_ts` after startup and on a timer. Each sweep uses:

- bounded delete batches (default 5,000 rows);
- a PostgreSQL transaction advisory lock for multi-replica safety;
- `ix_notifications_retention (is_read, created_at)`;
- failure isolation so cleanup errors never take the Social API offline.

Environment controls:

```text
NOTIFICATION_RETENTION_READ_DAYS=14
NOTIFICATION_RETENTION_UNREAD_DAYS=30
NOTIFICATION_RETENTION_SWEEP_HOURS=24
NOTIFICATION_RETENTION_BATCH_SIZE=5000
NOTIFICATION_RETENTION_MAX_BATCHES=20
```

An admin can request a sweep manually through:

```text
POST /api/notifications/admin/retention/sweep
```

Use `./tests/api/test_12_notifications.py` for the boundary test.
