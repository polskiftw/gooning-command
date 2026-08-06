import tempfile
import unittest
from pathlib import Path

from deduper.evidence_store import EvidenceStore, InventoryRecord


class EvidenceMetadataCheckpointTests(unittest.TestCase):
    def test_restore_rolls_back_identity_but_keeps_reusable_edges_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(Path(directory) / "evidence.sqlite3")
            original = [InventoryRecord("a.jpg", 10, "a", "1")]
            store.replace_inventory_snapshot(original)
            store.set_state("loosest_complete_slider", "25")
            checkpoint = store.metadata_checkpoint()

            store.replace_inventory_snapshot([InventoryRecord("b.jpg", 20, "b", "2")])
            store.set_state("loosest_complete_slider", "0")
            store.set_state("build_status", "complete")
            store.restore_metadata(checkpoint)

            self.assertTrue(store.inventory_matches(original))
            self.assertEqual(store.inventory_count(), 1)
            self.assertEqual(store.loosest_complete_slider(), 25)
            self.assertEqual(store.get_state("build_status"), "empty")
            store.close()

    def test_scan_architecture_restores_metadata_without_promotion(self) -> None:
        smart = Path("deduper/smart_app.py").read_text()
        self.assertIn("evidence_checkpoint = self.evidence.metadata_checkpoint()", smart)
        self.assertIn("self.evidence.restore_metadata(evidence_checkpoint)", smart)
        self.assertIn("evidence_promoted = True", smart)


if __name__ == "__main__":
    unittest.main()
