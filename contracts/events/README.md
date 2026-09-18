# MReader event contracts

These contracts are language-neutral and shared by Python, Go and TypeScript services.
MReader v1.2 publishes transactional-outbox events to the RabbitMQ topic exchange
`mreader.events`. Operational jobs use the separate direct exchange `mreader.jobs`.

## Envelope

Every event message body uses `event-envelope.schema.json`.

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "chapter.published",
  "event_version": 1,
  "aggregate_type": "chapter",
  "aggregate_id": "chapter-uuid",
  "occurred_at": "2026-08-27T00:00:00Z",
  "producer": "scraper-service",
  "correlation_id": null,
  "causation_id": null,
  "payload": {},
  "metadata": {}
}
```

The `topic` column in `registry.tsv` is the RabbitMQ routing key. The stable
`partition_key` remains in PostgreSQL/outbox metadata for idempotency, logical
ordering and a future broker migration, but RabbitMQ routing does not depend on
partition semantics.

## Compatibility policy

For a fixed `event_type` + `event_version`:

- adding an optional payload field is allowed;
- changing/removing a required field is breaking;
- changing a field's meaning/type is breaking;
- breaking changes require incrementing `event_version` and adding a new schema;
- consumers must ignore envelope `metadata` entries they do not understand.

## Payload rules

- no image bytes;
- no ZIP/PDF bodies;
- no secrets, session IDs or passwords;
- carry UUIDs, small metadata, and object-storage paths;
- keep events idempotent by stable `event_id`;
- use UTC ISO-8601 timestamps.

The database additionally caps outbox `payload` JSONB at 1 MiB.
