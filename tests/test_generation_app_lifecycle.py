from __future__ import annotations

import sqlite3
import unittest

from deduper.generation_app_lifecycle import GenerationAppLifecycle
from deduper.generation_identity import GenerationValidation, ValidationState
from deduper.generation_integration import GenerationStartupState
from deduper.generation_store import GenerationIdentity, GenerationStore
from deduper.startup_validation import StartupPhase, StartupSnapshot


class Value:
    def __init__(self, value=0):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeDatabase:
    def __init__(self):
        self.projected = []

    def replace_pairs(self, pairs, *, preserve_exclusions=False):
        self.projected = list(pairs)
        return len(self.projected)


class FakeApp:
    def __init__(self):
        self.database = FakeDatabase()
        self.store = object()
        self.slider = Value(50)
        self.status = Value("")
        self.pairs = []
        self.pair_index = 0
        self._inventory_verified_for_delete = False
        self._slider_guard = False
        self.after_calls = []
        self.action_refreshes = 0
        self.review_refreshes = []
        self.boundary_refreshes = 0
        self.scan_starts = 0

    def start_scan(self):
        self.scan_starts += 1

    def after(self, delay_ms, callback):
        self.after_calls.append((delay_ms, callback))

    def _refresh_pairs(self):
        self.pairs = list(self.database.projected)

    def _set_action_state(self):
        self.action_refreshes += 1

    def _set_review_state(self, enabled):
        self.review_refreshes.append(enabled)

    def _refresh_index_boundary(self, *, apply):
        self.boundary_refreshes += 1


class GenerationAppLifecycleTests(unittest.TestCase):
    def make_store(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE assets (key TEXT PRIMARY KEY, size INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE pairs (
                id INTEGER PRIMARY KEY,
                left_key TEXT NOT NULL,
                right_key TEXT NOT NULL
            );
            INSERT INTO assets (key) VALUES ('A'), ('B'), ('C');
            """
        )
        return GenerationStore(connection)

    def make_active(self, store):
        identity = GenerationIdentity(
            inventory_fingerprint="fp",
            inventory_object_count=3,
            slider_value=37,
            matcher_version="certified-matcher-v1",
            hash_version="phash-crop-pdq-vpdq-v1",
            workflow_version="certified-generation-v1",
        )
        generation_id = store.create_staging(identity)
        store.replace_staging_pairs(
            generation_id,
            [
                (0, "g", "A", "B", 99.0, "match"),
                (1, "g", "A", "C", 98.0, "match"),
            ],
        )
        store.complete_staging(generation_id)
        store.promote(generation_id)
        store.set_queue_position(generation_id, 1)
        return store.active()

    def test_install_projects_saved_generation_and_restores_slider_and_position(self):
        store = self.make_store()
        active = self.make_active(store)
        app = FakeApp()
        startup = GenerationStartupState(store, active, None)

        lifecycle = GenerationAppLifecycle(app, startup).install()

        self.assertEqual(app.slider.get(), 37)
        self.assertEqual(app.pair_index, 1)
        self.assertEqual(len(app.pairs), 2)
        self.assertFalse(app._inventory_verified_for_delete)
        self.assertIn("deletion locked", app.status.get())
        self.assertEqual(len(app.after_calls), 1)
        self.assertIsNotNone(lifecycle.coordinator)

    def test_validated_snapshot_unlocks_destructive_actions(self):
        store = self.make_store()
        active = self.make_active(store)
        app = FakeApp()
        lifecycle = GenerationAppLifecycle(app, GenerationStartupState(store, active, None))
        validation = GenerationValidation(ValidationState.VALIDATED, True, "ok")
        snapshot = StartupSnapshot(
            StartupPhase.VALIDATED_ACTIONABLE,
            active,
            validation,
            (),
        )

        lifecycle._apply_snapshot(snapshot)

        self.assertTrue(app._inventory_verified_for_delete)
        self.assertIn("deletion enabled", app.status.get())
        self.assertEqual(app._startup_inventory_snapshot, ())

    def test_rebuild_snapshot_preserves_view_but_keeps_deletion_locked(self):
        store = self.make_store()
        active = self.make_active(store)
        app = FakeApp()
        lifecycle = GenerationAppLifecycle(app, GenerationStartupState(store, active, None))
        validation = GenerationValidation(
            ValidationState.INVENTORY_CHANGED,
            False,
            "The current R2 inventory differs from the certified queue inventory.",
        )
        snapshot = StartupSnapshot(
            StartupPhase.REBUILD_REQUIRED,
            active,
            validation,
            (),
        )

        lifecycle._apply_snapshot(snapshot)

        self.assertFalse(app._inventory_verified_for_delete)
        self.assertIn("view-only", app.status.get())
        self.assertIn("deletion locked", app.status.get())
        self.assertEqual(len(app.after_calls), 1)
        delay, callback = app.after_calls[0]
        self.assertEqual(delay, 0)
        callback()
        self.assertEqual(app.scan_starts, 1)


if __name__ == "__main__":
    unittest.main()
