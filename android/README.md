# Mreader Android — RC4.84

## RC4.85 source work in progress

The unqualified RC4.85 changes keep the existing launcher name, artwork and version values. They require the matching RC4.85 backend and must not be released with an older Progress API.

Reading has one local owner, `ReadingRepository`. It captures an open and scroll intent immediately in memory, saves a scoped journal off the UI thread, and only uploads an exact command after that command is durable. Open retries keep their UUID/revision; checkpoint retries keep UUID/session/sequence/payload. Successful ACKs clear only their own generation. Rejected commands remain visibly paused. Normal uploads are dirty-only at 30 seconds, with end, exit, foreground and network-recovery flushes; local writes coalesce at one second. A failed local save is shown as memory-only and never claimed as durable.

The journal retains up to 500 pending records / 5 MiB per account and origin; it never evicts unsynced work to make space. Confirmed previews expire after seven days. Guest checkpoints stay guest-only. Automatic authentication loss suspends private pending work; explicit Sign out warns before discarding it. All queued reading requests carry the captured `X-MReader-Account-ID`; cookies still authorize them. Device time is never used to reorder server progress.

Reader restore checks the actual canonical chapter and does not reset a user gesture after a slow response. End-of-chapter completion requires an observed end and successful decoding of the chapter's published pages. Browse, Series and Library can preview a pending Continue action without changing server-confirmed counts or read markers. Recently Opened comes from the same versioned Smart Library envelope. Unknown envelopes are treated as unavailable; pagination advances using the server offset, independently of displayed-row deduplication.

API, protected media and the Web reader use the origin configured by the installed build. Obsolete hidden gateway/CDN preferences are ignored and retired. Cookies, cached identity and metadata are now namespaced by that origin; the first upgrade requires sign-in again. Old unscoped reading preferences are never uploaded as a newly signed-in account.

Validation is incomplete: the static Android integration audit passes, but this workspace has no Kotlin/Gradle/Android build toolchain. `ReadingJournalTest` covers rejection, ACK races, immutable retries, completion after scrolling back, mismatched ACKs, stale duplicate opens, unchanged checkpoints, scope identity, startup IO ordering and retention. Run the Android build and these tests, then exercise airplane mode/restart, full storage, slow restore, account switching, failed pages and conflict recovery on a device before release. See `docs/qualification/RC485-WORK-IN-PROGRESS.md` in the repository root.

RC4.84 keeps the consolidated mobile contracts and continuity-safe recovery model: Smart Library is the single library/history view, chapter-scoped Reader grants are mandatory, protected pages use encoding v4 only, and the native reader fetches protected bytes only through the mobile Reader adapter. The hidden direct `/images` compatibility transport is removed. The launcher identity remains `Mreader` / `ver.1.1.0`, with build code 484.

Native Android client for the existing MReader user gateway.

## Network stack

RC4.57 replaces the hand-written JSON HTTP layer with the standard Android stack:

- Retrofit 3.0.0 — declarative API contract (`MReaderApiService`)
- OkHttp 5.4.0 — HTTPS, HTTP/2, connection pooling, encrypted cookies and transport retries
- `MReaderApiAdapter` — bounded response reads, binary/image requests, detailed connection errors and gateway diagnostics
- EncryptedCookieJar — Android Keystore-backed MReader session cookie persistence

No reflection JSON framework is used. Existing lightweight `JSONObject` parsers remain behind the Retrofit adapter, avoiding Moshi/Kotlin-reflect overhead.

The default gateway is:

```text
https://overlord.seahorse-banded.ts.net
```

Settings exposes a compact **Connection** status and refresh action. The underlying diagnostics validate health plus Catalog/Auth reachability without showing gateway/CDN addresses in the normal mobile UI. DNS, TLS, timeout, gateway, Catalog-route, and Auth-route failures remain distinguishable internally.

RC4.73 keeps Catalog/Search/Series metadata and cover images in bounded local caches for smooth navigation. Signed-in readers additionally receive the 24-hour encoded chapter cache; Settings shows aggregate local-data usage and provides **Clear downloaded data**.

On a physical phone, obsolete saved emulator origins (`10.0.2.2`, `localhost`, `127.0.0.1`) from earlier APKs are migrated to the current public gateway. This prevents an APK upgrade from silently retaining an emulator-only URL.

## Build APK

From the repository root with Docker Desktop running:

```bash
./build-android-apk.sh
```

Output:

```text
dist/Mreader-ver.1.1.0-debug.apk
```

The Docker build installs/provides JDK, Gradle and Android SDK dependencies. The Windows host only needs Docker Desktop and Git Bash.

## Install on a phone

Copy the debug APK to the phone and install it, or use ADB:

```bash
adb install -r dist/Mreader-ver.1.1.0-debug.apk
```

The debug APK is suitable for direct testing. Use a permanently signed release APK/AAB for user distribution.
