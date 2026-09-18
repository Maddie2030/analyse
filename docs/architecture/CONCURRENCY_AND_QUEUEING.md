# MReader scraper concurrency and queueing

RC4.28 is designed for multiple administrators to submit scraper work concurrently.

## Concurrency model

- PostgreSQL is the durable source of truth for every operation.
- RabbitMQ carries compact job references and uses durable quorum queues.
- Deliveries are at-least-once; workers atomically claim durable rows before work.
- One scraper-series worker pod has a bounded concurrency of 2 by default.
- Discovery, staging, batch publish and single-chapter publish each have multiple consumers, but all share one process-wide semaphore.
- KEDA can scale the scraper-series worker to 2 pods and the image-heavy batch worker to 2 pods.
- Two different series can therefore stage and/or publish concurrently.
- Publishing for the same series draft is serialized by a PostgreSQL advisory lock.
- Repeated submissions for the same source URL are coalesced under a transaction-scoped source lock and reuse the existing active operation.
- Chapter and series production tables retain unique constraints, providing a final database-level duplicate guard.

## Expected examples

Supported concurrently:

- Series A staging + Series B staging.
- Series A publishing + Series B publishing.
- Series A staging + Series B publishing.
- Two administrators submitting unrelated series simultaneously.

Serialized intentionally:

- Two publishers trying to publish the same series draft.
- Batch and single-chapter publication against the same draft.
- Duplicate requests for the same source URL while an active operation already exists.

## Resource policy

The local Docker Desktop profile is intentionally bounded for a 16 GB host. Increasing KEDA maxima or worker concurrency should be done only after measuring memory pressure, image sizes and PostgreSQL connection usage.
