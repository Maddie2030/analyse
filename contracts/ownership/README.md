# MReader ownership route contract

`routes.v1.json` is the versioned semantic ownership contract for **current source routes only**. It does not create routes, grant database privileges, alter gateway exposure, or replace `tests/api/endpoint_coverage.tsv`.

## Authority split

- `scripts/tests/api-route-audit.py` discovers the canonical current HTTP route set and validates route-specific endpoint evidence.
- `routes.v1.json` declares semantic ownership: access plane, handler provenance, authentication, `permitted_writes`, dependencies, consumers, events, and acceptance gates.
- `scripts/tests/ownership-route-audit.py` must pass against the same source tree before P09.3, P09.4, or P09.5 tooling may consume the contract.
- `reference/p09.2-manifest-wip` is historical evidence only and must never be copied wholesale.

## Identifier rules

Operations use stable lower-case dotted identifiers. PostgreSQL write resources use exact table names when the route directly owns mutation. Event resources use exact current event/topic names. Dependencies and consumers use normalized identifiers documented by the schema.

Internal routes never have browser consumers. Mutation routes must explicitly declare write authority unless a reviewed side-effect-free command exception is encoded by the auditor contract. Empty arrays mean no semantic fact has been proven for that dimension; they are preferable to invented data.

## Update workflow

When a route changes:

1. change the route source;
2. update `tests/api/endpoint_coverage.tsv` and executable evidence;
3. update `routes.v1.json` semantic declarations;
4. run both the route coverage audit and ownership route audit;
5. only then allow downstream P09.3+ consumers to use the manifest from the same source tree.
