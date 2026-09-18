# Reading ownership and commands

This contract belongs to the RC4.85 working branch. It requires migration 051 and matched Web/Android clients. Runtime qualification is tracked separately; do not use a successful source audit as evidence of a completed upgrade or restore.

| Fact | Persistent owner | Read interface |
| --- | --- | --- |
| Active resume chapter and checkpoint | Progress / `reading_progress` | Progress GET and `reading_state_v1` |
| Accepted last-open target and time | Progress / `reading_progress` | `reading_state_v1.last_opened_*` |
| Exact read and completion evidence | Progress / `chapter_reads` | Progress series state; furthest through `reading_state_v1` |
| Bookmark, subscription and rating | Social | Social commands and Library |
| Card membership, counts, recent rail and available action | Social's live query, no separate table | One `/api/social/library` response |
| Unsynced reading intent | One account/origin-scoped client repository | Local pending preview; never a global count |

## Wire contract

The gateway paths remain unchanged. `/open` accepts a UUID `command_id` and the last observed `expected_revision`. `/commit` accepts its own UUID `command_id`, the accepted `session_generation`, a positive `command_sequence`, `last_page`, `scroll_position`, `completed`, and `completed_page`. Both mutations require `X-MReader-Account-ID` containing the account captured with the queued intent; Progress compares it with the authenticated session before target lookup and returns HTTP 403 with `code:account_mismatch` when it is absent or different. The header is only a freshness fence and never supplies identity. Progress GET/history/state routes make the same comparison when the header is supplied, while headerless direct reads remain compatible. The schemas in this directory describe the bounded request bodies.

Completion evidence is separate from resume: after reaching the end, a reader may scroll back to page one while still sending `completed:true, completed_page:<published page count>`. Merely viewing the top of the last page or obtaining a manifest does not imply completion. The server validates the target and page count; clients must observe the chapter end and successful media loading. Completion never changes back to false on a reread.

Each new client command requires a fresh UUID, and a transmitted command body is immutable across retries. The server retains only the latest checkpoint identity/hash and latest open identity per chapter; it does not keep a permanent command log. An exact retry of the retained identity is deduplicated, and an older exact retry remains fenced by revision, session, or sequence. Once an identity is superseded, reuse with a new sequence or revision is outside the server's historical-uniqueness guarantee and can be treated as a new command. Checkpoint hashing uses the validated submitted body; only afterward does the transaction clamp the stored page to the published target, so two different submitted pages that clamp to the same stored page still conflict when they reuse the retained sequence and ID.

Both commands return the canonical series resume plus `revision`, `session_generation`, `command_sequence`, `last_opened_at`, `accepted`, `duplicate`, `code`, and the echoed `command_id`. A command response is successful persistence only when `accepted:true` is received after commit. Transport timeout and Beacon acceptance are not acknowledgements. HTTP 200 with `accepted:false` is an explicit synchronization conflict, not success.

| Result code | Meaning | Client response |
| --- | --- | --- |
| `accepted` | Transaction committed | Acknowledge only the matching pending generation |
| `duplicate` | The same accepted command was already applied | Reconcile returned state without creating new activity |
| `revision_conflict` | A newer open/state revision exists | Keep local intent; ask the reader to reconcile |
| `stale_session` | Another accepted open owns resume | Preserve local intent and pause; never reopen automatically |
| `stale_sequence` | A later checkpoint was already accepted | Preserve/reconcile; do not overwrite the later position |
| `command_conflict` | A retained sequence or command ID was reused with different content | Pause; retain evidence for diagnosis |

Exact chapter evidence from a recognized older session can be retained without giving it resume ownership. Every changed projection receives a new revision and transactional outbox event. `progress.updated` v2 contains the canonical revision; its chapter ID is null if the former resume target was deleted. Events invalidate projections; they do not own reading facts.

GET `/api/progress/{series}/{chapter}` returns the current **series** resume. A client must compare its `chapter_id` with the requested manifest before restoring its page. Opening a different chapter selects only that chapter's valid checkpoint, if known. Server revision and session/sequence rules arbitrate ordering; client timestamps do not.

## Library consistency

Items, summary, filtered total, and the global recent rail are selected in one PostgreSQL statement from the Progress-owned view. The response includes `contract_version:1`, `generated_at`, `request_identity`, `recently_opened:{items,total}`, and per-card `reading_revision`, `reading_available`, and typed `reading_action`. The recent rail is limited to twelve unique series. Every sort has a unique series-ID tie-breaker. An unavailable query is an error, not a successful zero-count Library.

Updates means published chapters after furthest reached. Caught up does not claim every chapter is complete. Local pending previews may show a device's current page but must not change those server-owned totals or invent read markers.

## Upgrade and verification

Apply through the serialized migration runner after the approved safety backup and while mutation services are stopped. Migration 051 preserves available matching legacy checkpoints, including a ledger-only selected resume and a newer ledger checkpoint selected over an older resume, reconciles old last-open evidence once, and creates the normal `reading_state_v1` view. Those selected checkpoints remain available after opening another chapter and returning. A deleted current chapter clears the target while retaining the series revision fence and other ledger evidence.

Normal runtime never starts a Progress stream flusher or reads the old Progress cache. The optional `PROGRESS_GO_DRAIN_LEGACY_STREAM=1` mode is a maintenance-only process: it disables the HTTP command server. Stop other mutation replicas before using it, verify the old stream has drained, then terminate it and restart without the flag. Legacy messages cannot overwrite a resume already owned by a new session. Mixed-version mutation deployments are not supported by this cutover.

Behavioral acceptance is in `tests/api/test_26_reading_commands.py`, supplemented by the existing Reader, Library and outbox capability tests. Run those against actual disposable PostgreSQL/services. Web queue tests use `node --test tests/regression/test_web_reading_repository.mjs`. Go tests, Web/Social builds, Android compilation/tests, real migration fixtures, and browser IndexedDB tests are separate required gates.
