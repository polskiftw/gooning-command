from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
from pathlib import Path

MAGIC = b"GPHBEN01"
HEADER = struct.Struct("<8sQ")
RECORD = struct.Struct("<QQQQQB7x")


def _hex_u64(value: str | None) -> tuple[int, bool]:
    if not value:
        return 0, False
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or len(text) > 16:
        return 0, False
    try:
        return int(text, 16), True
    except ValueError:
        return 0, False


def _hex_u256(value: str | None) -> tuple[tuple[int, int, int, int], bool]:
    if not value:
        return (0, 0, 0, 0), False
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or len(text) > 64:
        return (0, 0, 0, 0), False
    try:
        text = text.zfill(64)
        words = tuple(int(text[offset : offset + 16], 16) for offset in range(0, 64, 16))
        return (words[0], words[1], words[2], words[3]), True
    except ValueError:
        return (0, 0, 0, 0), False


def export_database(database: Path, output: Path) -> tuple[int, int, int, int]:
    database = database.resolve()
    output = output.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")

    uri = f"file:{database.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            """
            SELECT phash, pdq_hash
            FROM assets
            WHERE deleted = 0 AND (phash IS NOT NULL OR pdq_hash IS NOT NULL)
            ORDER BY key
            """
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        total = phash_count = pdq_count = rejected = 0
        with output.open("wb") as handle:
            handle.write(HEADER.pack(MAGIC, 0))
            for phash_text, pdq_text in rows:
                phash, has_phash = _hex_u64(phash_text)
                pdq, has_pdq = _hex_u256(pdq_text)
                if not has_phash and not has_pdq:
                    rejected += 1
                    continue
                flags = (1 if has_phash else 0) | (2 if has_pdq else 0)
                handle.write(RECORD.pack(phash, *pdq, flags))
                total += 1
                phash_count += int(has_phash)
                pdq_count += int(has_pdq)
            handle.seek(0)
            handle.write(HEADER.pack(MAGIC, total))
    finally:
        connection.close()

    return total, phash_count, pdq_count, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description="Export deduper hashes without modifying the database.")
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    try:
        total, phash_count, pdq_count, rejected = export_database(args.database, args.output)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Exported records : {total:,}")
    print(f"pHash records    : {phash_count:,}")
    print(f"PDQ records      : {pdq_count:,}")
    print(f"Rejected records : {rejected:,}")
    print(f"Binary input     : {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
