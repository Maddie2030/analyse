# Catalog publication contract v1

Status: executable Python wire/evidence contract and literal conformance fixtures. The private Catalog HTTP command, durable Media evidence migration, Catalog receipt transaction and caller cutover are **not implemented by this contract package**. Existing publishers still need P06.3–P06.6 integration. Passing the pure contract tests does not close PUB-01 or PUB-02.

## Private interface and ownership

| Planned method/path | Purpose | Authority |
| --- | --- | --- |
| `POST /internal/v1/catalog/publications` | Commit one validated create/replacement command. | Catalog admin writer only. |
| `GET /internal/v1/catalog/publications/{idempotency_key}` | Resolve an uncertain result using the stored receipt. | Catalog reads its durable result; ownership/actor authorization still required. |

Neither gateway exposes these routes. Workload authentication must identify the ingestion coordinator. The body retains `actor_id`, but a string in JSON is not authorization: Catalog must independently validate the retained requesting admin and active role, operation ownership, source revision, cancellation and ingestion fence. Persisted background operations do not depend on a browser cookie remaining alive.

The requesting coordinator sends only a command. It cannot submit a “verified” Media receipt or Catalog receipt alongside that command. Catalog loads Media evidence from the declared Media-owned read contract and its own receipts from its table. The pure Python matcher accepts those values as arguments to test the boundary; it does not prove their origin, object checksums or database persistence.

Media finishes conversion/upload and records immutable output evidence before publication. Ingestion owns the overall operation state and its `ingestion_generation`; Media owns its own `media_generation`. Those independent worker fences must not be collapsed into one counter. A completed Media subtask is not a published chapter.

## Command identity

`publication.schema.json` declares the complete command shape. Every field is required; optional values are explicit `null`. Unknown fields are rejected. UUIDs use canonical lowercase RFC-4122 v1–v5 form; integer counters are positive and at most 9,007,199,254,740,991. A create has `chapter_id=null` and `expected_revision=0`. A replacement identifies the chapter and its positive last observed revision, leaving room for the next revision. Chapter numbers are canonical nonnegative two-decimal strings, from `0.00` through `999999.99`, matching the database's precision without float coercion.

The immutable idempotency identity is the requesting operation plus `idempotency_key`, bound to **the whole submitted command** through `payload_sha256`. Actor, source revision, both fences, target/replacement revision, title and every manifest field are covered. Changing any of them is not an identical retry. Do not silently allocate a new key, rebase a stale revision or replace a queued body's digest in the retry loop.

## Bounded immutable output manifest

The manifest identifies the series ID, series/chapter slugs and complete ordered final page list. Each page includes primary output identity, byte count, SHA-256 and dimensions, v4 grid/seed, and either a complete responsive object or `null`.

- Wire command: at most **4 MiB**, including whitespace for raw input. Canonical bytes must also fit this bound.
- Final pages: **1–4096**, numbered consecutively from 1. Reject excess; never truncate. This is the final segmented-page bound, not the number of source archive images. Integration must report the limit before attempting Catalog commit.
- Dimensions: width 1–20,000; height 1–40,000. Rows and columns are 1–32, no larger than the respective image dimension. The per-axis limit matches the current PostgreSQL `ck_pages_encoding_metadata` constraint; the parsers permit a wider asymmetric grid provided its product is at most 1024. Encoder configuration currently permits some grids the database rejects. P06.3 must align that producer/storage mismatch before caller cutover; this checkpoint does not silently broaden only the wire validator.
- Responsive fields are all present or all absent (`null`). The derivative is smaller, has its own byte count/checksum, and must support the same per-page grid stored by the current DB/Reader contract. Media must inspect actual encoded metadata; unsupported differing grids cannot be silently flattened into one row.
- New publication seeds are 32 lowercase hex characters, as emitted by the current encoder. Existing published/recovery metadata is not rewritten by this new-input validator.
- Primary identity: `series_slug/chapter_slug/_v4/<asset-version>/<page:04d>.mrt`.
- Responsive identity: `series_slug/chapter_slug/_v4/<asset-version>/w<width>/<page:04d>.mrt`.
- Asset version uses the existing `asset_version_for_v4(seed)` algorithm. No arbitrary URL, host path, encoded traversal, path prefix guessing, `images/` prefix or slash normalization is accepted here. Paths are exact relative SeaweedFS object identities, at most 500 characters.

Media must hash the actual uploaded primary/derivative bytes and record verified immutable output evidence. A syntactically valid checksum is not evidence that those bytes exist. Catalog must compare its independently read Media receipt with the manifest digest, page count, actor, operation, source revision, Media operation and Media generation. It must reject incomplete, mismatched or unavailable evidence before mutation.

## Canonical digest bytes

The hash algorithm is explicitly part of v1; do not use a language's default JSON output without conformance tests.

1. Validate field/type/Unicode rules. Strings contain Unicode scalar values; lone UTF-16 surrogates are invalid. All numeric fields are integers. Do not accept booleans, decimal/exponent tokens, NaN or Infinity as numbers.
2. Serialize JSON with object keys sorted lexicographically, no whitespace, and unchanged array order. Keys in this contract are ASCII.
3. Escape strings using JSON escapes: quote/backslash, `\b`, `\f`, `\n`, `\r`, `\t`; other code points outside printable ASCII U+0020–U+007E use lowercase `\uXXXX`. Non-BMP values use a UTF-16 surrogate-pair escape. Slash, `<`, `>` and `&` remain literal. No Unicode normalization.
4. Encode that representation as ASCII and compute SHA-256, represented by 64 lowercase hex characters.
5. For `payload_sha256`, hash the command **without** its `payload_sha256` field. For Media `manifest_sha256`, hash the complete manifest only.

Whitespace/key ordering in a raw request do not change identity. Raw decoding rejects duplicate object keys, including escaped aliases, before a parser can discard their ambiguity. Schema checks alone cannot enforce lexical integer tokens, sequence order, seed/path matching, hash equality or evidence binding; the command boundary must execute these semantic checks.

Literal fixtures include Unicode and `<>&`/line-separator text to catch JSON-escaping mismatches. Expected hashes were generated with an independent Node reference before the Python implementation:

| Vector | SHA-256 |
| --- | --- |
| Manifest | `eda3b0711cb119f12b25d48913cecec4e911108d984b9afc07ffb75af3ffda45` |
| Unsigned command | `4a4de87cbc6e05845d033616a757bdf88bf83613dd901d711e95d5bcdf643488` |

Catalog's Go implementation must consume these same fixtures and pass before the route/caller switch. No Go compilation or cross-language server conformance pass is claimed yet.

Chapter `0.00` preserves the existing Scraper `normalize_chapter_number` capability. Current manual Catalog/Media entry points require a number greater than zero; P06.4 must align those entry points with the nonnegative canonical contract. This mismatch is recorded as remaining integration work, not hidden by rounding or rejecting existing zero-number chapters.

## Commit, retry and uncertain outcomes

The future Catalog transaction serializes receipt identity and target mutation. After authoritative actor/operation/fence/Media checks, it writes chapter/pages, incremented chapter/series revisions, the receipt, publication outbox event and exact replacement-cleanup intent atomically. No network conversion/upload occurs while those database locks are held.

`catalog-receipt.schema.json` describes only a committed result. An identical retry returns the stored chapter ID, revisions, page count and publication event ID. It does not emit another event or return an unrelated existing chapter merely because slug/number matches. A retained key with a changed digest is `idempotency_conflict`. A stored result inconsistent with its command is rejected as an invalid receipt.

A missing receipt does not mean an in-flight operation can never commit. A failed/timeout lookup does not mean it did not commit. The coordinator preserves objects and remains retryable/reconciling; it uses the same immutable command and the transaction's serialization guarantees to resolve uncertainty. Only the fenced cancellation protocol may decide no worker can still commit. Receipt replay still requires current authorization.

## Available functions and checks

The Python standard-library module is `shared.catalog_publication_contract`:

```python
sealed = seal_command(unsigned_command)
validated = decode_command(raw_http_body)
accepted = validate_media_evidence(validated, owner_loaded_media_receipt,
                                   actor_id=independently_authorized_admin_id)
replayed = replay_receipt(validated, owner_loaded_catalog_receipt,
                         actor_id=independently_authorized_admin_id)
```

`validate_command` accepts an already decoded command and `manifest_digest` hashes a validated manifest. All returned dicts are detached snapshots; none of these functions writes to PostgreSQL, publishes events, schedules work, deletes objects or authenticates credentials.

Run the actual Python behavior checks from the repository root:

```bash
python3 -m unittest discover -s tests/regression -p test_catalog_publication_contract.py -v
```

Errors expose a safe `PublicationContractError.code`: `invalid_command`, `invalid_manifest`, `request_too_large`, `manifest_too_large`, `payload_digest_mismatch`, `actor_mismatch`, `invalid_media_receipt`, `media_not_complete`, `media_evidence_mismatch`, `invalid_catalog_receipt`, `idempotency_conflict`. Future HTTP handlers add request/operation correlation IDs and appropriate status/retryability; these pure exceptions never echo filesystem paths or body contents.

Next integration work is P06.3, with private credential distribution prerequisite P09.1 before route wiring. Full tests must exercise the real Catalog transaction, Media persistence, concurrent publishers, response loss, cancellation, notifications and both gateway denials.
