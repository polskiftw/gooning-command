from __future__ import annotations

import unittest
from types import SimpleNamespace

from deduper.certified_app import CertifiedDeduperApp
from deduper.certified_queue import CertifiedFamily, CertifiedQueue
from deduper.generation_builder import CertifiedPairRow
from deduper.models import Asset, Pair


class ImmediateExecutor:
    def submit(self, callback, *args):
        callback(*args)
        return None


class FakeStatus:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class FakeStore:
    def __init__(self):
        self.deleted = []

    def delete_queued(self, queued):
        self.deleted.extend(key for key, _pair_id, _size in queued)
        results = [(key, pair_id, size, "deleted") for key, pair_id, size in queued]
        return results, [key for key, _pair_id, _size in queued], None


class FakeDatabase:
    def __init__(self, assets):
        self.assets = {asset.key: asset for asset in assets}
        self.projected = []
        self.reverse_records = []

    def asset(self, key):
        return self.assets.get(key)

    def record_reverse_deletion(self, deleted, protected, size, result):
        self.reverse_records.append((deleted, protected, size, result))
        self.assets[deleted].deleted = True

    def replace_pairs(self, rows, *, preserve_exclusions=False):
        self.projected = list(rows)
        return len(self.projected)

    def queue_index_cleanup(self, _deleted):
        raise AssertionError("unexpected index cleanup")


class FakeRepairQueue:
    def __init__(self):
        self.next_id = 1
        self.enqueued = []
        self.running = []
        self.completed = []
        self.retry = []

    def enqueue(self, deleted_key, protected_key, priority_keys):
        repair_id = self.next_id
        self.next_id += 1
        self.enqueued.append((repair_id, deleted_key, protected_key, tuple(priority_keys)))
        return repair_id

    def mark_running(self, repair_id):
        self.running.append(repair_id)
        return True

    def complete(self, repair_id):
        self.completed.append(repair_id)

    def mark_pending(self, repair_id, error=None):
        self.retry.append((repair_id, error))

    def pending(self):
        return ()


class Harness(CertifiedDeduperApp):
    def __init__(self, queue, pairs, assets):
        self.config = SimpleNamespace(allow_delete=True)
        self._inventory_verified_for_delete = True
        self.review_locked = False
        self.reverse_delete_busy = False
        self.pairs = pairs
        self.pair_index = 0
        self._active_certified_queue = queue
        self.database = FakeDatabase(assets)
        self._family_repair_queue = FakeRepairQueue()
        self.store = FakeStore()
        self.executor = ImmediateExecutor()
        self.status = FakeStatus()
        self.recertify_calls = []
        self.refreshes = 0

    def _set_action_state(self):
        pass

    def _set_review_state(self, _enabled):
        pass

    def _refresh_counts(self):
        pass

    def _refresh_pairs(self):
        self.refreshes += 1
        self.pairs = [
            Pair(index + 1, left, right, similarity, reason, "pending", None)
            for index, (left, right, similarity, reason) in enumerate(self.database.projected)
        ]
        self.pair_index = min(self.pair_index, max(0, len(self.pairs) - 1))

    def _ui(self, callback, *args):
        callback(*args)

    def _recertify_bye_bitch_family(self, repair_id, keys):
        self.recertify_calls.append((repair_id, tuple(keys)))
        self._family_repair_queue.complete(repair_id)


def asset(key):
    return Asset(key, 100, key, "now", "image", "jpg")


def row(group, left, right, score):
    return CertifiedPairRow(group, left, right, score, "match")


class ByeBitchBehaviorTests(unittest.TestCase):
    def make_harness(self):
        queue = CertifiedQueue()
        queue.admit_family(
            CertifiedFamily(
                "family-a",
                ("A", "1", "2"),
                (
                    row("family-a", "A", "1", 72.0),
                    row("family-a", "A", "2", 88.0),
                ),
            )
        )
        queue.admit_family(
            CertifiedFamily(
                "family-b",
                ("B", "3"),
                (row("family-b", "B", "3", 79.0),),
            )
        )
        pairs = [
            Pair(1, "A", "1", 72.0, "match", "pending", None),
            Pair(2, "B", "3", 79.0, "match", "pending", None),
            Pair(3, "A", "2", 88.0, "match", "pending", None),
        ]
        return Harness(queue, pairs, [asset("A"), asset("1"), asset("2"), asset("B"), asset("3")])

    def test_delete_left_removes_whole_family_and_repairs_protected_right_first(self):
        app = self.make_harness()
        app._bye_bitch("left")
        self.assertEqual(app.store.deleted, ["A"])
        self.assertEqual(app.database.reverse_records[0][:2], ("A", "1"))
        self.assertEqual(app._family_repair_queue.enqueued[0][1:], ("A", "1", ("1", "2")))
        self.assertEqual(app.recertify_calls, [(1, ("1", "2"))])
        self.assertEqual(app.database.projected, [("B", "3", 79.0, "match")])
        self.assertIsNone(app._active_certified_queue.family_for_asset("1"))
        self.assertIsNotNone(app._active_certified_queue.family_for_asset("B"))

    def test_delete_right_removes_whole_family_and_repairs_left_first(self):
        app = self.make_harness()
        app._bye_bitch("right")
        self.assertEqual(app.store.deleted, ["1"])
        self.assertEqual(app.database.reverse_records[0][:2], ("1", "A"))
        self.assertEqual(app._family_repair_queue.enqueued[0][1:], ("1", "A", ("A", "2")))
        self.assertEqual(app.recertify_calls, [(1, ("A", "2"))])
        self.assertEqual(app.database.projected, [("B", "3", 79.0, "match")])

    def test_actions_do_nothing_until_inventory_validation_succeeds(self):
        app = self.make_harness()
        app._inventory_verified_for_delete = False
        app._bye_bitch("left")
        self.assertEqual(app.store.deleted, [])
        self.assertEqual(app.database.reverse_records, [])
        self.assertEqual(app._family_repair_queue.enqueued, [])
        self.assertEqual(app.recertify_calls, [])

    def test_concrete_app_has_single_inheritance_owner(self):
        self.assertEqual(CertifiedDeduperApp.__bases__, (CertifiedDeduperApp.__mro__[1],))
        self.assertNotIn("Mixin", CertifiedDeduperApp.__name__)


if __name__ == "__main__":
    unittest.main()
