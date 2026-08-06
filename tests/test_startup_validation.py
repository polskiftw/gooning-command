from __future__ import annotations

import sqlite3
import unittest

from deduper.generation_identity import build_generation_identity
from deduper.generation_store import GenerationStore
from deduper.models import Asset
from deduper.startup_validation import (
    StartupPhase,
    StartupValidationCoordinator,
    startup_status_text,
)


def asset(key: str, *, etag: str = "etag") -> Asset:
    return Asset(
        key=key,
        size=100,
        etag=etag,
        last_modified="2026-08-05T00:00:00+00:00",
        media_type="image",
        extension="jpg",
    )


class FakeInventorySource:
    def __init__(self, assets: list[Asset] | None = None, error: Exception | None = None):
        self.assets = assets or []
        self.error = error
        self.calls = 0

    def list_assets(self) -> list[Asset]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.assets)


def store() -> GenerationStore:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE assets (
            key TEXT PRIMARY KEY,
            size INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.executemany(
        "INSERT INTO assets (key) VALUES (?)",
        [("gallery/a.jpg",), ("gallery/b.jpg",)],
    )
    return GenerationStore(connection)


def promote_generation(generations: GenerationStore, assets: list[Asset], slider: int = 37) -> str:
    generation_id = generations.create_staging(build_generation_identity(assets, slider))
    generations.complete_staging(generation_id)
    generations.promote(generation_id)
    return generation_id


class StartupValidationTests(unittest.TestCase):
    def test_initial_state_keeps_saved_queue_visible_and_locked(self) -> None:
        generations = store()
        assets = [asset("gallery/a.jpg")]
        promote_generation(generations, assets)

        coordinator = StartupValidationCoordinator(
            generations,
            FakeInventorySource(assets),
            37,
        )
        snapshot = coordinator.snapshot()

        self.assertEqual(snapshot.phase, StartupPhase.SAVED_QUEUE_LOCKED)
        self.assertTrue(snapshot.saved_queue_visible)
        self.assertFalse(snapshot.destructive_actions_enabled)

    def test_exact_snapshot_match_unlocks_saved_generation(self) -> None:
        generations = store()
        assets = [asset("gallery/a.jpg"), asset("gallery/b.jpg")]
        generation_id = promote_generation(generations, assets)
        source = FakeInventorySource(list(reversed(assets)))

        snapshot = StartupValidationCoordinator(generations, source, 37).validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.VALIDATED_ACTIONABLE)
        self.assertTrue(snapshot.destructive_actions_enabled)
        self.assertEqual(snapshot.saved_generation.generation_id, generation_id)
        self.assertEqual(source.calls, 1)
        self.assertEqual(tuple(item.key for item in snapshot.inventory), ("gallery/b.jpg", "gallery/a.jpg"))

    def test_inventory_change_keeps_saved_queue_view_only(self) -> None:
        generations = store()
        saved_assets = [asset("gallery/a.jpg")]
        promote_generation(generations, saved_assets)
        current_assets = [asset("gallery/a.jpg", etag="replacement")]

        snapshot = StartupValidationCoordinator(
            generations,
            FakeInventorySource(current_assets),
            37,
        ).validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.REBUILD_REQUIRED)
        self.assertTrue(snapshot.saved_queue_visible)
        self.assertFalse(snapshot.destructive_actions_enabled)
        self.assertTrue(snapshot.rebuild_required)

    def test_slider_change_requires_rebuild(self) -> None:
        generations = store()
        assets = [asset("gallery/a.jpg")]
        promote_generation(generations, assets, slider=37)

        snapshot = StartupValidationCoordinator(
            generations,
            FakeInventorySource(assets),
            42,
        ).validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.REBUILD_REQUIRED)
        self.assertIn("slider", snapshot.validation.reason.lower())

    def test_listing_failure_preserves_saved_queue_but_never_unlocks(self) -> None:
        generations = store()
        assets = [asset("gallery/a.jpg")]
        promote_generation(generations, assets)

        snapshot = StartupValidationCoordinator(
            generations,
            FakeInventorySource(error=RuntimeError("R2 unavailable")),
            37,
        ).validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.VALIDATION_FAILED)
        self.assertTrue(snapshot.saved_queue_visible)
        self.assertFalse(snapshot.destructive_actions_enabled)
        self.assertIn("R2 unavailable", snapshot.error)

    def test_no_saved_generation_requires_build(self) -> None:
        generations = store()

        snapshot = StartupValidationCoordinator(
            generations,
            FakeInventorySource([asset("gallery/a.jpg")]),
            37,
        ).validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.REBUILD_REQUIRED)
        self.assertFalse(snapshot.saved_queue_visible)
        self.assertFalse(snapshot.destructive_actions_enabled)

    def test_cancel_before_listing_never_calls_r2(self) -> None:
        generations = store()
        source = FakeInventorySource([asset("gallery/a.jpg")])
        coordinator = StartupValidationCoordinator(generations, source, 37)
        coordinator.cancel()

        snapshot = coordinator.validate_now()

        self.assertEqual(snapshot.phase, StartupPhase.CANCELLED)
        self.assertEqual(source.calls, 0)
        self.assertFalse(snapshot.destructive_actions_enabled)

    def test_literal_status_text_matches_lock_state(self) -> None:
        generations = store()
        assets = [asset("gallery/a.jpg")]
        promote_generation(generations, assets)
        coordinator = StartupValidationCoordinator(generations, FakeInventorySource(assets), 37)

        self.assertIn("deletion locked", startup_status_text(coordinator.snapshot()).lower())
        validated = coordinator.validate_now()
        self.assertIn("deletion enabled", startup_status_text(validated).lower())


if __name__ == "__main__":
    unittest.main()
