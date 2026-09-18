# Queue and worker topology

MReader isolates background work when isolation improves latency, retryability or resource control. It does not create one worker per endpoint.

| Work | Delivery / queue | Consumer | Why |
|---|---|---|---|
| Reading progress | Valkey Stream `progress:updates` | Progress Go flusher | absorbs high-frequency progress ingress and persists in batches/controlled concurrency |
| Scraper batch chapter ingestion | dedicated Valkey list | scraper batch worker | isolates many chapter downloads from API request workers |
| Full-series staging | `scraper:series:stage:queue` | series worker | long-running network/parse work |
| Full-series batch publish | `scraper:series:publish:queue` | series worker | durable publication/recovery |
| Single staged chapter publish | `scraper:series:chapter-publish:queue` | series worker | independent retry and repair |
| Media processing | durable PostgreSQL `media_operations` + ARQ/Valkey execution | media worker | database is source of truth; queue loss is recoverable |
| Lifecycle cleanup | durable cleanup rows | lifecycle worker | post-commit external cleanup must survive restarts |
| Kafka publication | PostgreSQL `event_outbox` | outbox relay | business requests remain broker-independent |

## Architecture rule

Create a separate queue/worker when work is expensive, long-running, independently retryable, failure-isolated, or needs a different concurrency/resource envelope. Keep short CRUD/domain transactions synchronous and use the outbox for asynchronous side effects. This keeps baseline container count/RAM lower and avoids queue latency for simple user actions.
