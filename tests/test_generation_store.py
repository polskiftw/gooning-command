from __future__ import annotations

import sqlite3
import unittest

from deduper.generation_store import GenerationIdentity, GenerationStore


def make_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE assets (
            key TEXT PRIMARY KEY,
            size INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE pairs (
            id INTEGER PRIMARY KEY,
            left_key TEXT NOT NULL,
            right_key TEXT NOT NULL
        );
        CREATE TABLE deletion_log (
            id INTEGER PRIMARY KEY,
            deleted_key TEXT NOT NULL
        );
        CREATE TABLE index_cleanup_queue (
            key TEXT PRIMARY KEY
        );
        """
    )
    connection.executemany(
        "INSERT INTO assets (key) VALUES (?)",
        [("A",), ("B",), ("C",), ("D",)],
    )
    return connection


def identity(fingerprint: str = "fp-1") -> GenerationIdentity:
    return GenerationIdentity(
        inventory_fingerprint=fingerprint,
        inventory_object_count=4,
        slider_value=37,
        matcher_version="matcher-v1",
        hash_version="hash-v1",
        workflow_version="workflow-v1",
    )


class GenerationStoreTests(unittest.TestCase):
    def test_migration_is_additive_and_preserves_existing_data(self) -> None:
        connection = make_connection()
        connection.execute(
            "INSERT INTO deletion_log (deleted_key) VALUES ('old-deletion')"
        )
        connection.execute(
            "INSERT INTO index_cleanup_queue (key) VALUES ('needs-cleanup')"
        )

        GenerationStore(connection)

        self.assertEqual(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 4)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM deletion_log").fetchone()[0], 1)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM index_cleanup_queue").fetchone()[0],
            1,
        )

    def test_legacy_queue_is_view_only_not_certified(self) -> None:
        connection = make_connection()
        connection.execute(
            "INSERT INTO pairs (left_key, right_key) VALUES ('A', 'B')"
        )
        store = GenerationStore(connection)

        generation_id = store.register_legacy_view_only()

        row = connection.execute(
            "SELECT state FROM certified_generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        self.assertEqual(row["state"], "legacy_view_only")
        self.assertIsNone(store.active())

    def test_staging_does_not_replace_active_until_atomic_promotion(self) -> None:
        connection = make_connection()
        store = GenerationStore(connection)

        first = store.create_staging(identity("fp-1"))
        store.replace_staging_pairs(
            first,
            [(0, "group-a", "A", "B", 99.0, "test")],
        )
        store.complete_staging(first)
        store.promote(first)

        second = store.create_staging(identity("fp-2"))
        store.replace_staging_pairs(
            second,
            [(0, "group-b", "C", "D", 98.0, "test")],
        )

        self.assertEqual(store.active().generation_id, first)
        self.assertEqual([row["deletion_key"] for row in store.pairs(first)], ["B"])

        store.complete_staging(second)
        store.promote(second)

        self.assertEqual(store.active().generation_id, second)
        first_state = connection.execute(
            "SELECT state FROM certified_generations WHERE generation_id = ?",
            (first,),
        ).fetchone()["state"]
        self.assertEqual(first_state, "retired")
        self.assertEqual([row["deletion_key"] for row in store.pairs(first)], ["B"])

    def test_incomplete_staging_cannot_be_promoted(self) -> None:
        connection = make_connection()
        store = GenerationStore(connection)
        staging = store.create_staging(identity())

        with self.assertRaisesRegex(ValueError, "incomplete"):
            store.promote(staging)

        self.assertIsNone(store.active())

    def test_deletion_candidate_can_appear_only_once(self) -> None:
        connection = make_connection()
        store = GenerationStore(connection)
        staging = store.create_staging(identity())

        with self.assertRaisesRegex(ValueError, "only once"):
            store.replace_staging_pairs(
                staging,
                [
                    (0, "group-a", "A", "B", 99.0, "test"),
                    (1, "group-a", "C", "B", 98.0, "test"),
                ],
            )

    def test_survivor_can_appear_in_multiple_pairs_and_sha_is_generation_scoped(self) -> None:
        connection = make_connection()
        store = GenerationStore(connection)
        staging = store.create_staging(identity())
        store.replace_staging_pairs(
            staging,
            [
                (0, "group-a", "A", "B", 99.0, "test"),
                (1, "group-a", "A", "C", 98.0, "test"),
            ],
        )
        store.replace_staging_sha_deletions(staging, [(0, "A", "D")])
        store.complete_staging(staging)
        store.promote(staging)

        self.assertEqual(
            [row["survivor_key"] for row in store.pairs(staging)],
            ["A", "A"],
        )
        self.assertEqual(
            [row["deletion_key"] for row in store.sha_deletions(staging)],
            ["D"],
        )

    def test_queue_position_belongs_to_certified_generation(self) -> None:
        connection = make_connection()
        store = GenerationStore(connection)
        staging = store.create_staging(identity())
        store.complete_staging(staging)
        store.promote(staging)

        store.set_queue_position(staging, 3)

        self.assertEqual(store.active().saved_queue_position, 3)


if __name__ == "__main__":
    unittest.main()
