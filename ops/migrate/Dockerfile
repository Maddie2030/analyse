FROM postgres:16.10-alpine3.22@sha256:029660641a0cfc575b14f336ba448fb8a75fd595d42e1fa316b9fb4378742297
COPY db/migrations /migrations
COPY db/upgrade /migration-safety
COPY ops/migrate /usr/local/lib/mreader/migrate
COPY ops/migrate/run.sh /run-migrations.sh
RUN chmod 0555 /run-migrations.sh
ENTRYPOINT ["/run-migrations.sh"]
