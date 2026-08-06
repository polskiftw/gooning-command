GPARTY NATIVE HAMMING BENCHMARK

1. Extract the downloaded ZIP.
2. Drag your deduper database file onto RUN-BENCHMARK.bat.
3. Let it finish.
4. Send Rin the entire Results section.

You may also double-click RUN-BENCHMARK.bat and paste the database path.

SAFETY
- Opens SQLite in read-only mode.
- Does not change the database.
- Does not contact R2.
- Does not alter pairs, certification, review state, or deletion queues.
- Creates one temporary packed-hash file and deletes it after the run.

The benchmark performs a deliberately exhaustive native pHash + PDQ pass using XOR and hardware POPCNT across all available logical CPU threads.
