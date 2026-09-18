# RC4.85 reference branches preserved for sequential review

Date: 2026-09-15

These refs are preserved inside the sequential review repository so useful prior work can be inspected or selectively ported without merging its history into the active sequential line.

| Ref | Tip | Purpose | Integration rule |
| --- | --- | --- | --- |
| `reference/p06.2-17c28ac-import` | `651ffe9` | Reconstructed P06.2 Catalog publication contract/fixtures/tests from the `17c28ac65f27314af65cc555dcefc6d62c82913b` checkpoint. | Use as source reference when sequential review reaches P06. Re-validate against then-current source; do not cherry-pick the cumulative WIP patch wholesale. |
| `reference/p09.1-scoped-secrets` | `343eda6` | Reverse-order P09.1 workload-scoped Kubernetes secret implementation. | Re-review after P06/P07/P08 replacement callers are established. Selectively port or cherry-pick only if still compatible. |
| `reference/p09.2-manifest-wip` | `b444163` | Continuation of the reverse P09 branch containing the RED ownership-route manifest regression test. | Keep RED until P09.2 sequential work creates the manifest. It is evidence/fixture work, not a completed feature. |
| `reference/p09-baseline` | `ac9cf4a` | Baseline of the imported reverse repo. | Provenance only. |
| `reverse-reference/reverse-p09` | `343eda6` | Remote-tracking copy of the imported reverse history. | Provenance/reference only. |
| `reverse-reference/milestone1-baseline` | `ac9cf4a` | Remote-tracking baseline of the imported reverse history. | Provenance/reference only. |

The stable patch-id of `reference/p09.1-scoped-secrets` is `ac975c01339b0f868951ea5da0eb994cdcb67cdd`, matching the previously exported P09.1 merge-unit patch. This confirms the imported branch preserves the same content even though the commit identifier differs from an earlier local reconstruction.

The exact `17c28ac...` Git commit object is not present in the available local repositories. Its useful P06.2 file set was reconstructed from the preserved WIP patch and independently verified before commit `651ffe9`.

## Active sequential line

The active work remains on `sequential/*` branches. Reference branches are intentionally not merged into it. Current sequential ordering remains P01 -> P02 -> P03 -> ... -> P12.
