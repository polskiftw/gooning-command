from __future__ import annotations

import unittest
from dataclasses import dataclass

from deduper.generation_identity import (
    HASH_VERSION,
    MATCHER_VERSION,
    WORKFLOW_VERSION,
    ValidationState,
    build_generation_identity,
    inventory_identity,
    validate_generation,
)
from deduper.generation_store import GenerationIdentity, GenerationRecord


@dataclass(frozen=True)
class Item:
    key: str
    size: int
    etag: str
    last_modified: str


ITEMS = [
    Item("gallery/a.jpg", 10, "etag-a", "2026-08-05T01:00:00Z"),
    Item("gallery/b.jpg", 20, "etag-b", "2026-08-05T02:00:00Z"),
]


class GenerationIdentityTests(unittest.TestCase):
    def test_inventory_identity_is_order_independent(self) -> None:
        forward = inventory_identity(ITEMS)
        reverse = inventory_identity(reversed(ITEMS))
        self.assertEqual(forward, reverse)
        self.assertEqual(forward.object_count, 2)

    def test_same_count_replacement_changes_fingerprint(self) -> None:
        original = inventory_identity(ITEMS)
        replacement = inventory_identity(
            [
                ITEMS[0],
                Item("gallery/c.jpg", 20, "etag-c", "2026-08-05T02:00:00Z"),
            ]
        )
        self.assertEqual(original.object_count, replacement.object_count)
        self.assertNotEqual(original.fingerprint, replacement.fingerprint)

    def test_metadata_change_changes_fingerprint(self) -> None:
        original = inventory_identity(ITEMS)
        changed = inventory_identity(
            [
                Item("gallery/a.jpg", 11, "etag-a2", "2026-08-05T03:00:00Z"),
                ITEMS[1],
            ]
        )
        self.assertNotEqual(original.fingerprint, changed.fingerprint)

    def test_builder_freezes_all_version_identity(self) -> None:
        identity = build_generation_identity(ITEMS, 37)
        self.assertEqual(identity.inventory_object_count, 2)
        self.assertEqual(identity.slider_value, 37)
        self.assertEqual(identity.matcher_version, MATCHER_VERSION)
        self.assertEqual(identity.hash_version, HASH_VERSION)
        self.assertEqual(identity.workflow_version, WORKFLOW_VERSION)

    def test_exact_identity_is_actionable(self) -> None:
        identity = build_generation_identity(ITEMS, 37)
        record = GenerationRecord("generation-1", "certified", identity, 0)
        result = validate_generation(record, identity)
        self.assertEqual(result.state, ValidationState.VALIDATED)
        self.assertTrue(result.actionable)

    def test_inventory_change_is_not_actionable(self) -> None:
        saved = build_generation_identity(ITEMS, 37)
        current = build_generation_identity(
            [ITEMS[0], Item("gallery/c.jpg", 20, "etag-c", ITEMS[1].last_modified)],
            37,
        )
        result = validate_generation(
            GenerationRecord("generation-1", "certified", saved, 0),
            current,
        )
        self.assertEqual(result.state, ValidationState.INVENTORY_CHANGED)
        self.assertFalse(result.actionable)

    def test_each_software_identity_mismatch_is_explicit(self) -> None:
        current = build_generation_identity(ITEMS, 37)
        cases = [
            (
                GenerationIdentity(
                    current.inventory_fingerprint,
                    current.inventory_object_count,
                    38,
                    current.matcher_version,
                    current.hash_version,
                    current.workflow_version,
                ),
                ValidationState.SLIDER_CHANGED,
            ),
            (
                GenerationIdentity(
                    current.inventory_fingerprint,
                    current.inventory_object_count,
                    current.slider_value,
                    "old-matcher",
                    current.hash_version,
                    current.workflow_version,
                ),
                ValidationState.MATCHER_CHANGED,
            ),
            (
                GenerationIdentity(
                    current.inventory_fingerprint,
                    current.inventory_object_count,
                    current.slider_value,
                    current.matcher_version,
                    "old-hash",
                    current.workflow_version,
                ),
                ValidationState.HASH_CHANGED,
            ),
            (
                GenerationIdentity(
                    current.inventory_fingerprint,
                    current.inventory_object_count,
                    current.slider_value,
                    current.matcher_version,
                    current.hash_version,
                    "old-workflow",
                ),
                ValidationState.WORKFLOW_CHANGED,
            ),
        ]
        for saved, expected in cases:
            with self.subTest(expected=expected):
                result = validate_generation(
                    GenerationRecord("generation-1", "certified", saved, 0),
                    current,
                )
                self.assertEqual(result.state, expected)
                self.assertFalse(result.actionable)

    def test_legacy_and_missing_generations_are_view_only(self) -> None:
        current = build_generation_identity(ITEMS, 37)
        missing = validate_generation(None, current)
        legacy = validate_generation(
            GenerationRecord("legacy-1", "legacy_view_only", None, 0),
            current,
        )
        self.assertEqual(missing.state, ValidationState.NO_CERTIFIED_GENERATION)
        self.assertFalse(missing.actionable)
        self.assertEqual(legacy.state, ValidationState.LEGACY_UNTRUSTED)
        self.assertFalse(legacy.actionable)


if __name__ == "__main__":
    unittest.main()
