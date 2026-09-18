-- v1.2.0 RC6 notification-worker durability and realtime fan-out support.
--
-- RabbitMQ/outbox delivery is intentionally at-least-once. Persisting the
-- originating event id and a logical dedupe key makes notification creation
-- safe across broker redelivery, relay re-publication, and worker races.

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS source_event_id UUID NULL,
    ADD COLUMN IF NOT EXISTS kind VARCHAR(64) NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255) NULL;

ALTER TABLE notifications
    ALTER COLUMN message TYPE VARCHAR(2000);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_source_event_user
    ON notifications (source_event_id, user_id)
    WHERE source_event_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_dedupe_key
    ON notifications (user_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_notifications_source_event
    ON notifications (source_event_id)
    WHERE source_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notification_event_receipts (
    event_id UUID PRIMARY KEY,
    event_type VARCHAR(128) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    notifications_inserted INTEGER NOT NULL DEFAULT 0
        CHECK (notifications_inserted >= 0),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_notification_event_receipts_processed
    ON notification_event_receipts (processed_at DESC);

COMMENT ON TABLE notification_event_receipts IS
    'Idempotency receipts for RabbitMQ notification events. Inserted in the same transaction as notification rows.';
COMMENT ON COLUMN notifications.source_event_id IS
    'Originating MReader event id used for at-least-once consumer idempotency and realtime fan-out.';
COMMENT ON COLUMN notifications.dedupe_key IS
    'Logical per-user notification key; prevents duplicate effects when equivalent events have different event ids.';
