from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deduper.edge_rules import edge_qualifies
from deduper.evidence_qualification import mark_edges_qualified, qualified_edge_rows
from deduper.evidence_store import EvidenceEdge, EvidenceStore


class EdgeRulesTests(unittest.TestCase):
    def screenshot_edge(self) -> EvidenceEdge:
        return EvidenceEdge(
            "gallery/a.jpg",
            "gallery/b.jpg",
            phash_distance=26,
            pdq_distance=120,
            crop_similarity=60.0,
            evidence_mask=7,
        )

    def test_sixty_percent_crop_cannot_qualify_at_strict_99(self) -> None:
        self.assertFalse(edge_qualifies(self.screenshot_edge(), 99))

    def test_same_edge_may_qualify_only_at_an_explicitly_loose_position(self) -> None:
        self.assertTrue(edge_qualifies(self.screenshot_edge(), 0))

    def test_bad_strict_edge_is_never_written_to_qualification_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(Path(directory) / "evidence.sqlite3")
            try:
                edge = self.screenshot_edge()
                store.upsert_edges([edge])
                self.assertEqual(mark_edges_qualified(store, [edge], 99), 0)
                self.assertEqual(qualified_edge_rows(store, 99), [])
            finally:
                store.close()

    def test_stale_bad_row_is_filtered_even_if_old_code_marked_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(Path(directory) / "evidence.sqlite3")
            try:
                edge = self.screenshot_edge().normalized()
                store.upsert_edges([edge])
                store.connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS edge_qualification (
                        left_key TEXT NOT NULL,
                        right_key TEXT NOT NULL,
                        first_qualified_slider INTEGER NOT NULL,
                        PRIMARY KEY (left_key, right_key)
                    )
                    """
                )
                store.connection.execute(
                    "INSERT INTO edge_qualification VALUES (?, ?, 99)",
                    (edge.left_key, edge.right_key),
                )
                store.connection.commit()
                self.assertEqual(qualified_edge_rows(store, 99), [])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
