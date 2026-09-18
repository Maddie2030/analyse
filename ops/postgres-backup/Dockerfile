FROM golang:1.25.0-alpine3.22 AS recovery-bridge-builder
WORKDIR /src
COPY ops/postgres-backup/recovery_bridge/main.go ./main.go
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/mreader-recovery-bridge main.go

FROM postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297
RUN apk add --no-cache \
    'bash>=5.2.37' \
    'jq>=1.8.1' \
    'coreutils>=9.7' \
    'tzdata>=2026a'
COPY --from=recovery-bridge-builder /out/mreader-recovery-bridge /usr/local/bin/mreader-recovery-bridge
COPY scripts/backup/backup-agent.sh /usr/local/bin/mreader-backup-agent
COPY scripts/backup/local-recovery-store.sh /usr/local/bin/mreader-local-recovery-store
COPY scripts/backup/sync-local-recovery-catalog.sh /usr/local/bin/mreader-sync-recovery-catalog
COPY db/migrations /migrations
COPY db/upgrade /migration-safety
COPY ops/migrate /usr/local/lib/mreader/migrate
RUN chmod 0755 /usr/local/bin/mreader-recovery-bridge /usr/local/bin/mreader-backup-agent /usr/local/bin/mreader-local-recovery-store /usr/local/bin/mreader-sync-recovery-catalog
ENTRYPOINT ["/usr/local/bin/mreader-backup-agent"]
CMD ["daemon"]
