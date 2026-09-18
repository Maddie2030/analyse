# RC4.85 Sequential Review — Baseline Provenance

**Sequential review base:** `mreader-rc485-milestone-1-source-test.zip`
**Package SHA-256:** `958e15800c53c95735c5f02412841d40eb17971d6ddd4d129752b46cdd4bb34c`
**Embedded source checkpoint:** `9a2415002983ea79915d7fb0a8a6cd2d83150fc0`
**Recorded source baseline:** `7d6b74c`
**Runtime labels in this milestone:** `1.3.0-rc4.84`
**Sequential repository baseline commit:** `4f142ed`
**17c28ac reference-only import commit:** `651ffe9`

This repository is a new review repository. The uploaded package and recovered historical artifacts are not modified in place. Reference imports live below `reference/` and are not copied over application paths until the relevant sequential task is reached and requalified.

## Approved archive identities

The approved ownership/consolidation specification records these original source archives as the provenance set. They are recorded here for P01 continuity; the original four archives are not all mounted in this review workspace, so their hashes are **recorded evidence**, not freshly re-hashed by this run.

| Archive | Recorded SHA-256 | Role |
| --- | --- | --- |
| `mreader-rc481-history-public-metrics-reliability(6).zip` | `1188d087c7335bb0cda45218ff474fe8b6dc2751d67775ecac6c14deb41b65fb` | Behavioral reference; retain user/admin capabilities, public aggregates, reading/history continuity, notifications, scraping and restore behavior where still required. |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r2(1).zip` | `98aca244ba406b46c04392763bf2b9ff16a0714988f0ab411bd92c11f4921de7` | Application/upgrade recovery corrections to port selectively with tests. |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r4(1).zip` | `fe302f271e3929b78f89f0577d8eab366c943a8fa24ab0556fd7b269c3dff27e` | Intermediate infrastructure comparison; not an independent runtime target. |
| `mreader-v1.3.0-rc4.84-continuity-recovery-r5(1).zip` | `ab48e524e80c803913a992a3c46f2e936a4bcf238c43ada3975de79227885376` | Recorded source-tree starting baseline before the later RC4.85 work. |

## Milestone-1 integrity evidence

The currently uploaded Milestone-1 package was freshly hashed in this workspace and matches the previously recorded ZIP digest exactly:

```text
958e15800c53c95735c5f02412841d40eb17971d6ddd4d129752b46cdd4bb34c  mreader-rc485-milestone-1-source-test(3).zip
```

`SOURCE-CHECKPOINT.json` identifies the package as an application-source-test checkpoint at source commit `9a2415002983ea79915d7fb0a8a6cd2d83150fc0`, based on `7d6b74c`. It explicitly does not claim a compiled APK, prebuilt images, or a qualified final release.

`CHECKSUMS.sha256` is the authoritative per-file package manifest for this ZIP. Fresh verification result: **729/729 entries passed**.

## Historical source-manifest drift

`SOURCE_SHA256SUMS.txt` is retained for historical source-state evidence, but it is **not** the current package-integrity manifest. Fresh verification against the Milestone-1 tree produced:

- **582** entries matching;
- **85** entries with changed content;
- **4** listed paths no longer present.

This is expected for a historical source manifest after later committed changes, but it must not be described as proving current package integrity. Release/package verification uses `CHECKSUMS.sha256` for this milestone and a newly generated exact-tree manifest at later packaging gates.

## Recovered `17c28ac` checkpoint material

The saved `mreader-rc485-WIP-source-changes.patch` was recovered from prior project files. It is a cumulative WIP delta containing changes from multiple RC4.85 tasks, many of which are already present in Milestone 1; therefore the complete patch is **not** applied to this baseline.

The 13 P06.2 files absent from Milestone 1 were reconstructed under `reference/imports/17c28ac/tree/` only. Each reconstructed file matches the Git blob ID in the patch. In a disposable overlay they reproduced the recorded source-only contract evidence: Python compilation passed, **28/28** focused Catalog publication-contract tests passed, and all four schemas plus four fixtures parsed. These files remain reference material until sequential review reaches P06.

## P01 provenance disposition

- Original uploaded/recovered artifacts remain unchanged.
- The review baseline is source commit `9a241500...` as delivered in Milestone 1.
- The new Git repository has independent commit history and does not reuse historical commit IDs as its own commits.
- `17c28ac` is evidence/reference, not the active working-tree identity.
- Runtime/build gates remain distinct from source provenance and are not promoted by this report.
