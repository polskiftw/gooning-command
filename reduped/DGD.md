# Reduped Developer Guide

This is the implementation guide for the native first release. Product behavior is governed by the project handoff; this file maps that behavior to concrete ownership.

## Ownership

| Concern | Owner |
|---|---|
| Runtime settings and deletion safety | `Config` |
| Inventory/evidence/generation persistence | `Database` |
| Complete comparison pass | `match_all` |
| Direct-edge family orientation | `construct_generation` |
| Startup reconciliation and atomic publication | `CertificationPipeline` |
| Single and batch remote actions | `DeletionService` |
| S3-compatible transport and index mutation | `WinHttpObjectStore` |
| Native still/GIF/video evidence | `WindowsEvidenceGenerator` |
| Control state and stale preview rejection | Win32 `App` |

Critical behavior has one owner. There are no mixins, monkey patches, widget replacement passes, or manual scan lifecycle.

## Certification identity

A generation identity contains the deterministic inventory fingerprint, slider value, hash version, matcher version, and workflow version. A staging generation becomes actionable only after its assets, families, pairs, and exact deletion set are committed and transactionally promoted.

The previous certified generation remains active while staging is incomplete or failed.

## Evidence

Evidence is keyed by object identity and hash implementation version. The slider is deliberately absent from this key. A changed object or changed hash version produces new evidence without destroying historical rows.

The first native evidence version includes:

- SHA-256 over exact bytes;
- 64-bit DCT pHash;
- 256-bit robust DCT hash stored as PDQ evidence;
- overlapping regional pHashes for crop resistance;
- sampled 256-bit frame hashes for GIFs and video;
- dimensions, duration, and a visual quality measure.

Very short videos use denser sampling. Animated images are sampled across their complete frame range up to the configured cap.

## Family construction

Connected components organize candidate edges, but queue rows are created only for measured edges. Each review family is a direct-evidence star around its chosen survivor. If a connected component has no single safe survivor adjacent to every member, it is conservatively split. A deletion candidate appears once; the survivor may appear in multiple rows.

Exact-byte groups are removed from visual review and placed in the generation's exact deletion set.

## Destructive sequence

Every click carries generation, family, pair, object keys, and revision. The database revalidates all of them.

For a survivor deletion, the protected partner and priority members are persisted in an `awaiting_remote` recertification job before the remote request. A failed remote request cancels that intent without changing the family. A successful remote request activates the job, hides only that family, and records index cleanup independently.

Prepared actions resume after a crash. A missing object is accepted as completion only during recovery of an already-persisted action.

## Database

Reduped tables use the `rd_` prefix, allowing the application to open an existing deduper database without deleting or reinterpreting legacy tables. Existing uncertain queues never become certified by migration.

SQLite runs in WAL mode with foreign keys, full synchronous commits, integrity validation, partial unique indexes for active generations and unfinished repair jobs, and transactional promotion.

## Testing

`reduped_tests` exercises inventory identity, reconciliation, certification isolation, unchanged startup, direct-edge graph semantics, exact separation, actionability, stale clicks, both deletion sides, survivor repair, failure truthfulness, idempotent recovery, exclusive claims, index retry, batch plans, and preview revision races.

`reduped_benchmark` is separate from the GUI. Its optional argument is the generated record count.

## Version changes

Increment the hash version when decoding, preprocessing, serialization, or hash meaning changes. Increment the matcher version when threshold curves or evidence interpretation changes. Increment the workflow version when family, survivor, orientation, exclusion, or destructive meaning changes.
