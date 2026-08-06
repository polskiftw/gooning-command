# Native Hamming Benchmark

This is a separate, read-only experiment for measuring how quickly the desktop CPU can exhaustively compare the hashes already stored in a GParty deduper SQLite database.

It does **not** modify the database, create review pairs, alter certification state, delete files, or contact R2.

## Run it

Open PowerShell in the repository root and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\deduper\native_benchmark\run-benchmark.ps1 -DatabasePath "C:\path\to\your\deduper.db"
```

The runner will:

1. Find MSVC or g++.
2. Compile the native C++ benchmark with CPU optimizations.
3. Open the SQLite database in read-only mode.
4. Export active pHash and PDQ values to a temporary packed binary file.
5. Exhaustively compare every record pair using native XOR and hardware POPCNT.
6. Print elapsed time, comparison throughput, and match counts.
7. Delete the temporary export.

By default it uses all logical processors reported by Windows and the loosest current deduper radii:

- pHash radius: 18 bits
- PDQ radius: 48 bits

Optional example:

```powershell
powershell -ExecutionPolicy Bypass -File .\deduper\native_benchmark\run-benchmark.ps1 `
  -DatabasePath "C:\path\to\your\deduper.db" `
  -Threads 32 `
  -PHashRadius 18 `
  -PDQRadius 48
```

## What this benchmark answers

This intentionally uses a blunt exhaustive triangular scan rather than a BK-tree or bucket index. It answers the first and most useful question:

> Is packed native XOR/POPCNT already fast enough on the real database that a sophisticated search index is unnecessary?

If the result is already measured in seconds or a few minutes, the production matcher can use this native core directly or add only light candidate filtering. If it remains too slow at larger sizes, the same native verifier can sit behind a multi-index or bucketed candidate generator.

## Interpreting output

- `Elapsed` is wall-clock time for the native comparison pass.
- `Comparisons` is the number of unique unordered record pairs examined.
- `Rate` is millions of record pairs processed per second.
- `pHash matches` counts pairs within the requested 64-bit pHash radius.
- `PDQ matches` counts pairs within the requested 256-bit PDQ radius.
- `Either matches` counts the union of those two result sets.
- `Checksum` exists to ensure the compiler cannot optimize the distance calculations away.

The benchmark only measures the cheap fixed-width hash relationship pass. Crop-resistant hashes, vPDQ frame matching, group construction, SQLite writes, and preview generation are intentionally excluded so their costs can be measured separately after the core result is known.
