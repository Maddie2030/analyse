# MReader API pytest suite — current RC4 twin-plane

The API suite currently contains 22 modules and 92 collected tests, with the two real-internet scraper adapter tests excluded by default. It targets the current Docker Desktop Kubernetes twin-plane deployment directly.

## Gateways used by the Docker runner

```text
user:  http://host.docker.internal:8080
admin: http://host.docker.internal:8081
```

Those host ports terminate at the current Kubernetes user/admin gateways, so the tests still exercise the deployed twin-plane application end to end while avoiding test-pod NetworkPolicy interference. Regular-user API tests go through the user gateway. Admin ingestion/write and RBAC tests go through the admin gateway. Admin sessions are created on the admin plane so cookie scope matches the gateway being tested.

## Major coverage

1. user/admin gateway routing and isolation
2. registration, login, Session Contract, profile and admin RBAC
3. Catalog reads/search/filters/curation/admin writes
4. Reader manifests, chapter grants and protected image delivery
5. Progress/history/exact chapter-read ownership
6. bookmarks, subscriptions, ratings and Smart Library
7. comments and notification behavior
8. durable Media jobs and lifecycle deletion
9. existing-series and new-series Scraper workflows
10. cancel/recovery/operation dashboard semantics
11. outbox/event atomicity and SQL bind contracts

The Smart Library tests use Progress commits; Reader GETs are explicitly verified as read-only.

## Run

Full suite:

```bash
./scripts/run-pytest-api.sh
```

One module:

```bash
./scripts/run-one-pytest-module.sh test_08_progress.py
```

Both commands build the pytest Docker image locally and execute it as an ordinary Docker container attached to the hybrid stateful network. No host Python installation is required.

## External scraper tests

Two tests that contact real public source sites remain opt-in and are excluded from the normal suite. The default regression suite uses local/deterministic data and SSRF-rejection cases instead.
