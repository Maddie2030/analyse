#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
fail(){ echo "diagnostics dependency snapshot regression FAILED: $*" >&2; exit 1; }
F=scripts/diagnostics/collect-runtime-evidence.sh
for needle in 'postgres-connectivity' 'schema_migrations' 'event_outbox' 'ingestion_operations' 'database_operations' 'rabbitmq-diagnostics' 'rabbitmqctl list_queues' 'valkey-cli ping' 'valkey-cli info memory' 'gateway-user-health' 'gateway-admin-health' 'seaweedfs-health'; do grep -Fq "$needle" "$F" || fail "missing dependency evidence: $needle"; done
! grep -Eiq 'rabbitmqctl[[:space:]]+(purge_queue|delete_queue|delete_vhost)|redis-cli[[:space:]].*(flushall|flushdb)|valkey-cli[[:space:]].*(flushall|flushdb)' "$F" || fail 'destructive queue/cache command present'
! grep -Eiq 'psql[^\n]*(-c|--command)[^\n]*(delete|update|insert|truncate|drop|alter)[[:space:]]' "$F" || fail 'destructive/mutating SQL present'
echo 'diagnostics dependency snapshot regression PASS'
