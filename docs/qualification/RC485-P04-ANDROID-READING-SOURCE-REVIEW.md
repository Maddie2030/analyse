# RC4.85 P04 Android reading/origin sequential review

Date: 2026-09-15

## Scope

This checkpoint re-qualifies the already-implemented Android reading journal and one-origin policy against the RC4.85 ownership specification. It does not claim a full Android build, emulator/device upgrade rehearsal, or independent review.

## Source findings

- `ReadingRepository` is the single native pending-reading owner. Its scope key contains both configured origin and account identity.
- Pending commands are bounded to 500 records / 5 MiB, persisted before transport, retried without mutating an in-flight command, and synchronized at a dirty-only 30-second interval plus explicit flushes.
- Automatic authentication expiry suspends private pending intent rather than reassigning it to the guest/current account. Explicit logout warns when unsynced intent exists and only then removes private journal data.
- `ServerConfigStore` never reads legacy `base_url` / `image_cdn_url` preferences. It removes them in the one-time policy migration and uses only the build-configured gateway origin.
- Android History/Recently Opened derives from the Smart Library contract. The legacy Retrofit declaration for `/api/progress/history` has no Android runtime caller and is not used to reconstruct Library truth.
- Native protected-page rendering and prefetch use `/api/mobile/v1/reader/.../page/...` with the chapter-scoped grant. 401/403 refreshes the chapter grant. There is no per-page-token or direct protected `/images` fallback.
- The WebView fallback uses the same configured gateway origin, copies only the current native session cookies to that origin, rejects navigation to another host, disables third-party cookies, file/content access, and mixed content.
- Protected encoded-byte cache identity includes the configured origin. Logout/session invalidation clears chapter grants and protected/private caches.

A stale comment in `MReaderRepository.fetchReaderPageBytes` still described an older direct `/images` fallback. The implementation did not contain that fallback; this checkpoint corrects the comment to match the enforced mobile-adapter contract.

## Verification reproduced here

- `python3 -m unittest tests.regression.test_rc485_p04_android_source -v` — 8/8 source ownership/origin audits passed.
- Direct `kotlinc` compilation of `Models.kt` + `ReadingJournal.kt` plus the temporary behavioral runner — 11/11 journal cases passed, reproducing the behaviors in `ReadingJournalTest.kt` without Gradle.
- `bash tests/regression/rc484-consolidation-static.sh` — passed.
- `bash tests/regression/api-flow-ownership-static.sh` — passed.
- `android/gradlew -p android testDebugUnitTest --no-daemon` — **blocked**: no Gradle installation is present and the wrapper cannot resolve `services.gradle.org` to download Gradle 9.6.0.

Environment observed: Java 21 and `kotlinc` 1.9.0 available; Gradle and ADB unavailable. The Milestone-1 source intentionally remains Android build code 484 until the final RC4.85 release gate.

## Status

P04.1 is source-qualified in the sequential review. P04.2 remains open for the real Gradle build/unit suite, obsolete-origin upgrade rehearsal, process-death/reconnect/device behavior, and independent review. AND-01 is not closed by this source checkpoint.
