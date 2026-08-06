import tempfile
import unittest
from pathlib import Path

from deduper.certified_database import CertifiedDatabase
from deduper.family_recertification_queue import FamilyRecertificationQueue


class FamilyRecertificationSchemaMigrationTests(unittest.TestCase):
    def test_legacy_schema_is_migrated_and_removed_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = CertifiedDatabase(Path(directory) / "deduper.sqlite3")
            with db.connection:
                db.connection.executescript("""
                    CREATE TABLE family_repair_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        deleted_key TEXT NOT NULL, protected_key TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempt_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                        last_attempt_at TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        completed_at TEXT
                    );
                    CREATE TABLE family_repair_members (
                        repair_id INTEGER NOT NULL
                            REFERENCES family_repair_jobs(id) ON DELETE CASCADE,
                        priority INTEGER NOT NULL, asset_key TEXT NOT NULL,
                        PRIMARY KEY (repair_id, asset_key),
                        UNIQUE (repair_id, priority)
                    );
                    INSERT INTO family_repair_jobs
                        (id, deleted_key, protected_key, status, attempt_count, last_error)
                    VALUES (7, 'gone.jpg', 'keep.jpg', 'retry', 3, 'saved failure');
                    INSERT INTO family_repair_members (repair_id, priority, asset_key)
                    VALUES (7, 0, 'keep.jpg'), (7, 1, 'other.jpg');
                """)
            queue = FamilyRecertificationQueue(db)
            pending = queue.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].recertification_id, 7)
            self.assertEqual(pending[0].priority_keys, ('keep.jpg', 'other.jpg'))
            self.assertEqual(pending[0].attempt_count, 3)
            self.assertEqual(pending[0].last_error, 'saved failure')
            names = {row['name'] for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            self.assertNotIn('family_repair_jobs', names)
            self.assertNotIn('family_repair_members', names)
            self.assertIn('family_recertification_jobs', names)
            self.assertIn('family_recertification_members', names)
            member_columns = {
                row['name']
                for row in db.connection.execute(
                    "PRAGMA table_info(family_recertification_members)"
                )
            }
            self.assertEqual(
                member_columns,
                {'recertification_id', 'priority', 'asset_key'},
            )
            FamilyRecertificationQueue(db)
            db.close()


if __name__ == '__main__':
    unittest.main()
