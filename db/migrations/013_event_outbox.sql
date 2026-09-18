-- v1.1.2 transactional event outbox.
--
-- IMPORTANT: this table is written in the SAME PostgreSQL transaction as the
-- business change. broker publication happens later in an outbox relay.
-- Therefore broker availability can never decide whether the business commit
-- succeeds.

CREATE TABLE IF NOT EXISTS event_outbox (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic VARCHAR(128) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1
        CHECK (event_version >= 1),
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(255) NOT NULL,
    partition_key VARCHAR(255) NOT NULL,
    producer VARCHAR(100) NOT NULL,
    correlation_id UUID NULL,
    causation_id UUID NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object'),
    headers JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(headers) = 'object'),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    last_error TEXT NULL,
    locked_at TIMESTAMPTZ NULL,
    locked_by VARCHAR(128) NULL,
    published_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Events are metadata messages, not blob transport. Keep payloads bounded
    -- and reference SeaweedFS/object paths for media instead.
    CONSTRAINT event_outbox_payload_size_check
        CHECK (octet_length(payload::text) <= 1048576),
    CONSTRAINT event_outbox_topic_nonempty
        CHECK (btrim(topic) <> ''),
    CONSTRAINT event_outbox_event_type_nonempty
        CHECK (btrim(event_type) <> ''),
    CONSTRAINT event_outbox_partition_key_nonempty
        CHECK (btrim(partition_key) <> ''),
    CONSTRAINT event_outbox_producer_nonempty
        CHECK (btrim(producer) <> '')
);

-- Relay claim path: unpublished rows that are eligible now, oldest first.
CREATE INDEX IF NOT EXISTS ix_event_outbox_pending
    ON event_outbox (available_at, created_at, event_id)
    WHERE published_at IS NULL;

-- Recovery/observability for rows currently claimed by a relay worker.
CREATE INDEX IF NOT EXISTS ix_event_outbox_locked
    ON event_outbox (locked_at)
    WHERE published_at IS NULL AND locked_at IS NOT NULL;

-- Useful for aggregate/event diagnostics and replay tooling.
CREATE INDEX IF NOT EXISTS ix_event_outbox_aggregate
    ON event_outbox (aggregate_type, aggregate_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_event_outbox_topic_created
    ON event_outbox (topic, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_event_outbox_published_cleanup
    ON event_outbox (published_at)
    WHERE published_at IS NOT NULL;

COMMENT ON TABLE event_outbox IS
    'Transactional event outbox. Business transactions insert here; an asynchronous relay publishes to the event broker.';
COMMENT ON COLUMN event_outbox.partition_key IS
    'Stable routing/ordering key used for a logical entity for a logical entity such as series_id or user_id.';
COMMENT ON COLUMN event_outbox.available_at IS
    'Earliest relay attempt time; used for retry backoff without blocking business transactions.';
COMMENT ON COLUMN event_outbox.published_at IS
    'Set only after the event broker confirms the event; NULL means relay work remains.';

-- Cross-language insert helper. Services call this from the SAME transaction as
-- their business write. The function only inserts PostgreSQL state; it never
-- contacts a message broker.
CREATE OR REPLACE FUNCTION enqueue_event_outbox_v1(
    p_topic TEXT,
    p_event_type TEXT,
    p_event_version INTEGER,
    p_aggregate_type TEXT,
    p_aggregate_id TEXT,
    p_partition_key TEXT,
    p_producer TEXT,
    p_payload JSONB,
    p_correlation_id UUID DEFAULT NULL,
    p_causation_id UUID DEFAULT NULL,
    p_headers JSONB DEFAULT '{}'::jsonb,
    p_occurred_at TIMESTAMPTZ DEFAULT NOW()
) RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_event_id UUID;
BEGIN
    INSERT INTO event_outbox (
        topic,
        event_type,
        event_version,
        aggregate_type,
        aggregate_id,
        partition_key,
        producer,
        correlation_id,
        causation_id,
        occurred_at,
        payload,
        headers
    ) VALUES (
        p_topic,
        p_event_type,
        p_event_version,
        p_aggregate_type,
        p_aggregate_id,
        p_partition_key,
        p_producer,
        p_correlation_id,
        p_causation_id,
        p_occurred_at,
        COALESCE(p_payload, '{}'::jsonb),
        COALESCE(p_headers, '{}'::jsonb)
    )
    RETURNING event_id INTO v_event_id;

    RETURN v_event_id;
END;
$$;

COMMENT ON FUNCTION enqueue_event_outbox_v1(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB,
    UUID, UUID, JSONB, TIMESTAMPTZ
) IS
    'Insert an MReader v1 event into the transactional outbox. Must be called inside the business transaction; never publishes to the event broker directly.';
