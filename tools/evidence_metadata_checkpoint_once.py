from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


store_path = Path("deduper/evidence_store.py")
store = store_path.read_text()
store = replace_once(
    store,
    '''@dataclass(frozen=True)
class EvidenceEdge:
''',
    '''@dataclass(frozen=True)
class EvidenceMetadataCheckpoint:
    inventory: tuple[InventoryRecord, ...]
    state: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class EvidenceEdge:
''',
    "checkpoint dataclass",
)
store = replace_once(
    store,
    '''    def replace_inventory_snapshot(self, records: Iterable[InventoryRecord]) -> str:
''',
    '''    def metadata_checkpoint(self) -> EvidenceMetadataCheckpoint:
        """Capture authoritative inventory and build-state metadata.

        Comparison edges are deliberately excluded: they are reusable evidence and
        may safely survive an abandoned build. The inventory identity and certified
        boundary are restored unless the replacement generation is promoted.
        """
        with self._lock:
            inventory_rows = self.connection.execute(
                """
                SELECT key, size, etag, last_modified
                FROM inventory_snapshot ORDER BY key
                """
            ).fetchall()
            state_rows = self.connection.execute(
                "SELECT key, value FROM cache_state ORDER BY key"
            ).fetchall()
        return EvidenceMetadataCheckpoint(
            inventory=tuple(
                InventoryRecord(
                    key=str(row["key"]),
                    size=int(row["size"]),
                    etag=str(row["etag"]),
                    last_modified=str(row["last_modified"]),
                )
                for row in inventory_rows
            ),
            state=tuple((str(row["key"]), str(row["value"])) for row in state_rows),
        )

    def restore_metadata(self, checkpoint: EvidenceMetadataCheckpoint) -> None:
        """Restore the active evidence identity after an unpromoted build."""
        with self._lock, self.connection:
            self.connection.execute("DELETE FROM inventory_snapshot")
            self.connection.executemany(
                """
                INSERT INTO inventory_snapshot (key, size, etag, last_modified)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (item.key, item.size, item.etag, item.last_modified)
                    for item in checkpoint.inventory
                ),
            )
            self.connection.execute("DELETE FROM cache_state")
            self.connection.executemany(
                "INSERT INTO cache_state (key, value) VALUES (?, ?)",
                checkpoint.state,
            )

    def replace_inventory_snapshot(self, records: Iterable[InventoryRecord]) -> str:
''',
    "checkpoint methods",
)
store_path.write_text(store)

smart_path = Path("deduper/smart_app.py")
smart = smart_path.read_text()
smart = replace_once(
    smart,
    '''            self.store.verify()
            inventory = self.store.list_assets()
            old_fingerprint = self.evidence.get_state("inventory_fingerprint")
''',
    '''            self.store.verify()
            inventory = self.store.list_assets()
            evidence_checkpoint = self.evidence.metadata_checkpoint()
            evidence_promoted = False

            def abandon_evidence(message: str) -> str:
                if not evidence_promoted:
                    self.evidence.restore_metadata(evidence_checkpoint)
                return message

            old_fingerprint = self.evidence.get_state("inventory_fingerprint")
''',
    "capture evidence metadata",
)
smart = replace_once(
    smart,
    '''                return (
                    f"Scan stopped safely. Saved {completed}/{len(pending)} completed objects; "
                    "unfinished objects will resume next scan. NUKE remains locked."
                )
''',
    '''                return abandon_evidence(
                    f"Scan stopped safely. Saved {completed}/{len(pending)} completed objects; "
                    "unfinished objects will resume next scan. Active evidence metadata was "
                    "restored and NUKE remains locked."
                )
''',
    "hash cancellation restore",
)
smart = replace_once(
    smart,
    '''                return (
                    f"Indexing stopped safely after {completed_bands} completed bands and "
                    f"{completed_groups} staged whole families; computed through slider "
                    f"{boundary_text}. Staging was not promoted; the previous certified queue "
                    "remains unchanged and NUKE remains locked."
                )
''',
    '''                return abandon_evidence(
                    f"Indexing stopped safely after {completed_bands} completed bands and "
                    f"{completed_groups} staged whole families; computed through slider "
                    f"{boundary_text}. Staging was not promoted; active evidence metadata and "
                    "the previous certified queue remain unchanged; NUKE remains locked."
                )
''',
    "index cancellation restore",
)
smart = replace_once(
    smart,
    '''                self._scan_completed_current_inventory = True
                safety_summary = (
''',
    '''                evidence_promoted = True
                self._scan_completed_current_inventory = True
                safety_summary = (
''',
    "mark evidence promoted",
)
smart = replace_once(
    smart,
    '''            elif errors:
                safety_summary = (
                    f"staging not promoted; previous certified queue retained; "
                    f"NUKE remains locked because {errors} hash errors remain"
                )
            else:
                safety_summary = (
                    "staging not promoted; previous certified queue retained; "
                    "NUKE remains locked because the full index is incomplete"
                )
            return (
''',
    '''            elif errors:
                self.evidence.restore_metadata(evidence_checkpoint)
                safety_summary = (
                    f"staging not promoted; active evidence metadata and previous certified "
                    f"queue retained; NUKE remains locked because {errors} hash errors remain"
                )
            else:
                self.evidence.restore_metadata(evidence_checkpoint)
                safety_summary = (
                    "staging not promoted; active evidence metadata and previous certified "
                    "queue retained; NUKE remains locked because the full index is incomplete"
                )
            return (
''',
    "nonpromotion restore",
)
smart_path.write_text(smart)

Path("tests/test_evidence_metadata_checkpoint.py").write_text('''import tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom deduper.evidence_store import EvidenceStore, InventoryRecord\n\n\nclass EvidenceMetadataCheckpointTests(unittest.TestCase):\n    def test_restore_rolls_back_identity_but_keeps_reusable_edges_table(self) -> None:\n        with tempfile.TemporaryDirectory() as directory:\n            store = EvidenceStore(Path(directory) / "evidence.sqlite3")\n            original = [InventoryRecord("a.jpg", 10, "a", "1")]\n            store.replace_inventory_snapshot(original)\n            store.set_state("loosest_complete_slider", "25")\n            checkpoint = store.metadata_checkpoint()\n\n            store.replace_inventory_snapshot([InventoryRecord("b.jpg", 20, "b", "2")])\n            store.set_state("loosest_complete_slider", "0")\n            store.set_state("build_status", "complete")\n            store.restore_metadata(checkpoint)\n\n            self.assertTrue(store.inventory_matches(original))\n            self.assertEqual(store.inventory_count(), 1)\n            self.assertEqual(store.loosest_complete_slider(), 25)\n            store.close()\n\n    def test_scan_architecture_restores_metadata_without_promotion(self) -> None:\n        smart = Path("deduper/smart_app.py").read_text()\n        self.assertIn("evidence_checkpoint = self.evidence.metadata_checkpoint()", smart)\n        self.assertIn("self.evidence.restore_metadata(evidence_checkpoint)", smart)\n        self.assertIn("evidence_promoted = True", smart)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
