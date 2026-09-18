#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source ./scripts/env/env-lib.sh

[[ -f .env ]] || { echo "ERROR: .env is required." >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required to initialize RabbitMQ topology." >&2; exit 2; }

env_value() {
  local key="$1" fallback="${2:-}" value
  value="$(env_get .env "$key")"
  value="${value%$'\r'}"
  case "$value" in
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
  esac
  [[ -n "$value" ]] || value="$fallback"
  printf '%s' "$value"
}

# The KEDA manifests intentionally use the fixed mreader vhost/queue contract.
# Fail early rather than silently provisioning a topology KEDA will never inspect.
RABBIT_USER="$(env_value RABBITMQ_USER mreader)"
RABBIT_PASS="$(env_value RABBITMQ_PASSWORD mreader)"
RABBIT_VHOST="$(env_value RABBITMQ_VHOST mreader)"
[[ "$RABBIT_VHOST" == "mreader" ]] || {
  echo "ERROR: Docker Desktop hybrid KEDA profile requires RABBITMQ_VHOST=mreader (got '$RABBIT_VHOST')." >&2
  exit 2
}

JOBS_EXCHANGE="$(env_value RABBITMQ_JOBS_EXCHANGE mreader.jobs)"
EVENTS_EXCHANGE="$(env_value RABBITMQ_EVENTS_EXCHANGE mreader.events)"
ARCHIVE_QUEUE="$(env_value RABBITMQ_EVENTS_ARCHIVE_QUEUE mreader.events.archive)"
NOTIFY_QUEUE="$(env_value NOTIFICATION_WORKER_QUEUE mreader.notification.worker)"
NOTIFY_RETRY_EXCHANGE="$(env_value NOTIFICATION_RETRY_EXCHANGE mreader.notification.retry)"
NOTIFY_RETRY_QUEUE="$(env_value NOTIFICATION_RETRY_QUEUE mreader.notification.worker.retry)"
NOTIFY_DEAD_EXCHANGE="$(env_value NOTIFICATION_DEAD_EXCHANGE mreader.notification.dead)"
NOTIFY_DEAD_QUEUE="$(env_value NOTIFICATION_DEAD_QUEUE mreader.notification.worker.dlq)"
RETRY_DELAY_MS="$(env_value RABBITMQ_RETRY_DELAY_MS 5000)"
NOTIFY_RETRY_DELAY_MS="$(env_value NOTIFICATION_RETRY_DELAY_MS "$RETRY_DELAY_MS")"
MGMT_PORT="$(env_value HYBRID_RABBITMQ_MANAGEMENT_PORT 15672)"
BIND_IP="$(env_value HYBRID_STATEFUL_BIND_IP 127.0.0.1)"
case "$BIND_IP" in
  0.0.0.0|::|"[::]") MGMT_HOST=127.0.0.1 ;;
  *) MGMT_HOST="$BIND_IP" ;;
esac
MGMT="http://${MGMT_HOST}:${MGMT_PORT}"

# These identifiers are embedded in URL paths/JSON below. Hybrid configuration
# intentionally keeps RabbitMQ topology names simple and deterministic.
for pair in \
  "RABBITMQ_JOBS_EXCHANGE:$JOBS_EXCHANGE" \
  "RABBITMQ_EVENTS_EXCHANGE:$EVENTS_EXCHANGE" \
  "RABBITMQ_EVENTS_ARCHIVE_QUEUE:$ARCHIVE_QUEUE" \
  "NOTIFICATION_WORKER_QUEUE:$NOTIFY_QUEUE" \
  "NOTIFICATION_RETRY_EXCHANGE:$NOTIFY_RETRY_EXCHANGE" \
  "NOTIFICATION_RETRY_QUEUE:$NOTIFY_RETRY_QUEUE" \
  "NOTIFICATION_DEAD_EXCHANGE:$NOTIFY_DEAD_EXCHANGE" \
  "NOTIFICATION_DEAD_QUEUE:$NOTIFY_DEAD_QUEUE"; do
  key="${pair%%:*}"; value="${pair#*:}"
  [[ "$value" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERROR: unsupported RabbitMQ topology name in $key: $value" >&2; exit 2; }
done
[[ "$RETRY_DELAY_MS" =~ ^[0-9]+$ ]] || { echo "ERROR: RABBITMQ_RETRY_DELAY_MS must be numeric." >&2; exit 2; }
[[ "$NOTIFY_RETRY_DELAY_MS" =~ ^[0-9]+$ ]] || { echo "ERROR: NOTIFICATION_RETRY_DELAY_MS must be numeric." >&2; exit 2; }

rabbit_curl() {
  curl -fsS --max-time 15 -u "${RABBIT_USER}:${RABBIT_PASS}" "$@"
}

# AMQP can be healthy slightly before the management HTTP listener is ready.
ready=0
for ((attempt=1; attempt<=30; attempt++)); do
  if rabbit_curl "${MGMT}/api/overview" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]] || {
  echo "ERROR: RabbitMQ management API is not reachable at $MGMT." >&2
  echo "Check the rabbitmq container and HYBRID_RABBITMQ_MANAGEMENT_PORT." >&2
  exit 3
}

put_exchange() {
  local name="$1" type="$2"
  rabbit_curl -H 'content-type: application/json' -X PUT \
    "${MGMT}/api/exchanges/mreader/${name}" \
    --data-binary "{\"type\":\"${type}\",\"durable\":true,\"auto_delete\":false,\"internal\":false,\"arguments\":{}}" >/dev/null
}

put_queue() {
  local name="$1" args="$2"
  rabbit_curl -H 'content-type: application/json' -X PUT \
    "${MGMT}/api/queues/mreader/${name}" \
    --data-binary "{\"durable\":true,\"auto_delete\":false,\"arguments\":${args}}" >/dev/null
}

bind_queue() {
  local exchange="$1" queue="$2" routing_key="$3"
  rabbit_curl -H 'content-type: application/json' -X POST \
    "${MGMT}/api/bindings/mreader/e/${exchange}/q/${queue}" \
    --data-binary "{\"routing_key\":\"${routing_key}\",\"arguments\":{}}" >/dev/null
}

JOBS_RETRY_EXCHANGE="${JOBS_EXCHANGE}.retry"
JOBS_DLX_EXCHANGE="${JOBS_EXCHANGE}.dlx"
put_exchange "$JOBS_EXCHANGE" direct
put_exchange "$JOBS_RETRY_EXCHANGE" direct
put_exchange "$JOBS_DLX_EXCHANGE" direct
put_exchange "$EVENTS_EXCHANGE" topic
put_exchange "$NOTIFY_RETRY_EXCHANGE" direct
put_exchange "$NOTIFY_DEAD_EXCHANGE" direct

# Queue workers are KEDA minReplicaCount=0. Their main queues MUST exist before
# KEDA can passively inspect queue length, otherwise scale-from-zero deadlocks.
JOB_QUEUES=(
  mreader.scraper.batch
  mreader.scraper.discovery
  mreader.scraper.stage
  mreader.scraper.publish
  mreader.scraper.chapter-publish
  mreader.media.chapter
  mreader.media.thumbnail
)
for queue in "${JOB_QUEUES[@]}"; do
  put_queue "$queue" '{"x-queue-type":"quorum"}'
  bind_queue "$JOBS_EXCHANGE" "$queue" "$queue"

  retry_queue="${queue}.retry"
  put_queue "$retry_queue" "{\"x-queue-type\":\"quorum\",\"x-message-ttl\":${RETRY_DELAY_MS},\"x-dead-letter-exchange\":\"${JOBS_EXCHANGE}\",\"x-dead-letter-routing-key\":\"${queue}\"}"
  bind_queue "$JOBS_RETRY_EXCHANGE" "$retry_queue" "$queue"

  dlq="${queue}.dlq"
  put_queue "$dlq" '{"x-queue-type":"quorum"}'
  bind_queue "$JOBS_DLX_EXCHANGE" "$dlq" "$queue"
done

# Declare notification topology before the worker can scale to zero so events
# published by the outbox relay already have durable consumer bindings.
put_queue "$NOTIFY_QUEUE" '{"x-queue-type":"quorum"}'
for routing_key in chapter.published notification.requested notification.worker.retry; do
  bind_queue "$EVENTS_EXCHANGE" "$NOTIFY_QUEUE" "$routing_key"
done

put_queue "$NOTIFY_RETRY_QUEUE" "{\"x-queue-type\":\"quorum\",\"x-message-ttl\":${NOTIFY_RETRY_DELAY_MS},\"x-dead-letter-exchange\":\"${EVENTS_EXCHANGE}\",\"x-dead-letter-routing-key\":\"notification.worker.retry\"}"
bind_queue "$NOTIFY_RETRY_EXCHANGE" "$NOTIFY_RETRY_QUEUE" notification.worker

put_queue "$NOTIFY_DEAD_QUEUE" '{"x-queue-type":"quorum"}'
bind_queue "$NOTIFY_DEAD_EXCHANGE" "$NOTIFY_DEAD_QUEUE" notification.worker

# Catch-all archive matches outbox-relay's startup topology and prevents events
# without an active feature consumer from disappearing during local development.
put_queue "$ARCHIVE_QUEUE" '{"x-queue-type":"quorum","x-message-ttl":604800000,"x-max-length":100000}'
bind_queue "$EVENTS_EXCHANGE" "$ARCHIVE_QUEUE" '#'

# Verify every KEDA-inspected main queue is visible before applying ScaledObjects.
for queue in "${JOB_QUEUES[@]}" "$NOTIFY_QUEUE"; do
  rabbit_curl "${MGMT}/api/queues/mreader/${queue}" >/dev/null || {
    echo "ERROR: RabbitMQ topology verification failed for queue: $queue" >&2
    exit 4
  }
done

echo "RabbitMQ hybrid topology initialized: KEDA queues + retry/DLQ/event bindings are ready."
