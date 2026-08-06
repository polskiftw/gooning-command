from __future__ import annotations

import sqlite3
import unittest

from deduper.generation_builder import (
    CertifiedGenerationBuilder,
    CertifiedPairRow,
    GenerationBuildCancelled,
    GenerationBuildPayload,
    ShaDeletionRow,
)
from deduper.generation_identity import build_generation_identity
from deduper.generation_store import GenerationStore
from deduper.models import Asset


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
        """
    )
    connection.executemany(
        "INSERT INTO assets (key, size) VALUES (?, ?)",
        [("A", 10), ("B", 20), ("C", 30), ("D", 40)],
    )
    return connection


def asset(key: str, size: int) -> Asset:
    return Asset(
        key=key,
        size=size,
        etag=f"etag-{key}",
        last_modified="2026-08-06T00:00:00+00:00",
        media_type="image",
        extension="jpg",
    )


INVENTORY = (asset("A", 10), asset("B", 20), asset("C", 30), asset("D", 40))


class CertifiedGenerationBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = make_connection()
        self.store = GenerationStore(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def install_old_active(self) -> str:
        old_id = self.store.create_staging(build_generation_identity(INVENTORY, 80))
        self.store.replace_staging_pairs(
            old_id,
            [(0, "old-group", "A", "B", 90.0, "old")],
        )
        self.store.complete_staging(old_id)
        self.store.promote(old_id)
        return old_id

    @staticmethod
    def payload(_inventory, _slider, _cancelled) -> GenerationBuildPayload:
        return GenerationBuildPayload(
            pairs=(
                CertifiedPairRow("group-1", "A", "C", 98.5, "visual"),
                CertifiedPairRow("group-1", "A", "D", 97.0, "visual"),
            ),
            sha_deletions=(ShaDeletionRow("A", "B"),),
        )

    def test_success_promotes_complete_staging_atomically(self) -> None:
        old_id = self.install_old_active()
        builder = CertifiedGenerationBuilder(self.store, INVENTORY, 75, self.payload)

        result = builder.build()

        self.assertNotEqual(result.generation.generation_id, old_id)
        self.assertEqual(result.pair_count, 2)
        self.assertEqual(result.sha_deletion_count, 1)
        self.assertEqual(result.generation.identity.slider_value, 75)
        self.assertEqual(
            [row["deletion_key"] for row in self.store.pairs(result.generation.generation_id)],
            ["C", "D"],
        )
        old_state = self.connection.execute(
            "SELECT state FROM certified_generations WHERE generation_id = ?",
            (old_id,),
        ).fetchone()["state"]
        self.assertEqual(old_state, "retired")

    def test_builder_receives_exact_materialized_inventory_snapshot(self) -> None:
        seen = []

        def capture(inventory, slider, _cancelled):
            seen.append((inventory, slider))
            return GenerationBuildPayload((), ())

        builder = CertifiedGenerationBuilder(self.store, iter(INVENTORY), 67, capture)
        builder.build()

        self.assertEqual(seen, [(INVENTORY, 67)])

    def test_failure_marks_staging_failed_and_keeps_old_active(self) -> None:
        old_id = self.install_old_active()

        def fail(_inventory, _slider, _cancelled):
            raise RuntimeError("comparison exploded")

        builder = CertifiedGenerationBuilder(self.store, INVENTORY, 75, fail)
        with self.assertRaisesRegex(RuntimeError, "comparison exploded"):
            builder.build()

        self.assertEqual(self.store.active().generation_id, old_id)
        failed = self.connection.execute(
            "SELECT state, failure_reason FROM certified_generations WHERE state = 'failed'"
        ).fetchone()
        self.assertEqual(failed["state"], "failed")
        self.assertIn("comparison exploded", failed["failure_reason"])

    def test_cancellation_before_build_never_creates_staging(self) -> None:
        old_id = self.install_old_active()
        builder = CertifiedGenerationBuilder(self.store, INVENTORY, 75, self.payload)
        builder.cancel()

        with self.assertRaises(GenerationBuildCancelled):
            builder.build()

        self.assertEqual(self.store.active().generation_id, old_id)
        staging_count = self.connection.execute(
            "SELECT COUNT(*) FROM certified_generations WHERE state = 'staging'"
        ).fetchone()[0]
        self.assertEqual(staging_count, 0)

    def test_cancellation_during_payload_keeps_old_active(self) -> None:
        old_id = self.install_old_active()
        holder = {}

        def cancel_during_build(_inventory, _slider, _cancelled):
            holder["builder"].cancel()
            return self.payload(_inventory, _slider, _cancelled)

        builder = CertifiedGenerationBuilder(
            self.store,
            INVENTORY,
            75,
            cancel_during_build,
        )
        holder["builder"] = builder

        with self.assertRaises(GenerationBuildCancelled):
            builder.build()

        self.assertEqual(self.store.active().generation_id, old_id)
        failed_count = self.connection.execute(
            "SELECT COUNT(*) FROM certified_generations WHERE state = 'failed'"
        ).fetchone()[0]
        self.assertEqual(failed_count, 1)

    def test_invalid_duplicate_deletion_candidate_cannot_promote(self) -> None:
        old_id = self.install_old_active()

        def duplicates(_inventory, _slider, _cancelled):
            return GenerationBuildPayload(
                pairs=(
                    CertifiedPairRow("g1", "A", "C", 99.0, "one"),
                    CertifiedPairRow("g2", "B", "C", 98.0, "two"),
                ),
                sha_deletions=(),
            )

        builder = CertifiedGenerationBuilder(self.store, INVENTORY, 75, duplicates)
        with self.assertRaisesRegex(ValueError, "only once"):
            builder.build()

        self.assertEqual(self.store.active().generation_id, old_id)


if __name__ == "__main__":
    unittest.main()
