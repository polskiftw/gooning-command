from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deduper.evidence_capture import (
    EVIDENCE_CROP,
    EVIDENCE_PDQ,
    EVIDENCE_PHASH,
    EVIDENCE_VPDQ,
    capture_pair_evidence,
    evidence_for_pairs,
)
from deduper.evidence_store import EvidenceStore
from deduper.models import Asset


def asset(
    key: str,
    *,
    phash: str | None = None,
    pdq: str | None = None,
    crop: list[str] | None = None,
    vpdq: list[dict[str, object]] | None = None,
) -> Asset:
    return Asset(
        key=key,
        size=100,
        etag="etag",
        last_modified="date",
        media_type="image" if vpdq is None else "video",
        extension="jpg" if vpdq is None else "mp4",
        phash=phash,
        pdq_hash=pdq,
        crop_hashes=json.dumps(crop) if crop is not None else None,
        vpdq_hashes=json.dumps(vpdq) if vpdq is not None else None,
    )


class EvidenceCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = EvidenceStore(Path(self.temp.name) / "evidence.sqlite3")

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_captures_raw_image_distances_and_crop_observation(self) -> None:
        left = asset(
            "gallery/a.jpg",
            phash="0000000000000000",
            pdq="0" * 64,
            crop=["0000000000000000"],
        )
        right = asset(
            "gallery/b.jpg",
            phash="0000000000000003",
            pdq=("0" * 63) + "3",
            crop=["0000000000000001"],
        )
        edges = evidence_for_pairs(
            [left, right],
            [(left.key, right.key, 95.0, "match")],
            99,
        )
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.phash_distance, 2)
        self.assertEqual(edge.pdq_distance, 2)
        self.assertEqual(edge.crop_similarity, 100.0)
        self.assertEqual(
            edge.evidence_mask,
            EVIDENCE_PHASH | EVIDENCE_PDQ | EVIDENCE_CROP,
        )

    def test_vpdq_direction_is_normalized_with_keys(self) -> None:
        shared = "0" * 64
        extra = "f" * 64
        left = asset(
            "gallery/z.mp4",
            vpdq=[{"h": shared, "q": 100}, {"h": extra, "q": 100}],
        )
        right = asset(
            "gallery/a.mp4",
            vpdq=[{"h": shared, "q": 100}],
        )
        edge = evidence_for_pairs(
            [left, right],
            [(left.key, right.key, 50.0, "video")],
            99,
        )[0].normalized()
        self.assertEqual(edge.left_key, "gallery/a.mp4")
        self.assertEqual(edge.right_key, "gallery/z.mp4")
        self.assertEqual(edge.vpdq_left_similarity, 1.0)
        self.assertEqual(edge.vpdq_right_similarity, 0.5)
        self.assertEqual(edge.evidence_mask, EVIDENCE_VPDQ)

    def test_repeat_capture_is_idempotent(self) -> None:
        left = asset("gallery/a.jpg", phash="0" * 16)
        right = asset("gallery/b.jpg", phash=("0" * 15) + "1")
        pairs = [(left.key, right.key, 98.0, "match")]
        capture_pair_evidence(self.store, [left, right], pairs, 99)
        capture_pair_evidence(self.store, [left, right], pairs, 99)
        self.assertEqual(self.store.edge_count(), 1)
        self.assertEqual(self.store.get_state("observed_edge_count"), "1")

    def test_observation_does_not_claim_slider_completion(self) -> None:
        left = asset("gallery/a.jpg", phash="0" * 16)
        right = asset("gallery/b.jpg", phash=("0" * 15) + "1")
        capture_pair_evidence(
            self.store,
            [left, right],
            [(left.key, right.key, 98.0, "match")],
            80,
        )
        self.assertIsNone(self.store.loosest_complete_slider())
        self.assertEqual(self.store.get_state("last_observed_slider"), "80")
        self.assertIsNotNone(self.store.get_state("last_observed_crop_cutoff"))
        self.assertIsNotNone(self.store.get_state("last_observed_vpdq_distance"))


if __name__ == "__main__":
    unittest.main()
