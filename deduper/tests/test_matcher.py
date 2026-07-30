from __future__ import annotations

import json
import unittest

from deduper.matcher import acquire_pairs, hamming_hex, thresholds, vpdq_similarity
from deduper.models import Asset


def asset(key: str, **values) -> Asset:
    base = Asset(
        key=key,
        size=100,
        etag="",
        last_modified="",
        media_type="image",
        extension="jpg",
    )
    for name, value in values.items():
        setattr(base, name, value)
    return base


class MatcherTests(unittest.TestCase):
    def test_hamming_hex(self) -> None:
        self.assertEqual(hamming_hex("00", "03"), 2)

    def test_exact_duplicates_always_match(self) -> None:
        shared = "f" * 64
        pairs = acquire_pairs(
            [
                asset("gallery/a.jpg", sha256=shared),
                asset("gallery/b.jpg", sha256=shared),
            ],
            99,
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][2], 100)

    def test_similar_phashes_match(self) -> None:
        pairs = acquire_pairs(
            [
                asset("gallery/a.jpg", sha256="a" * 64, phash="0000000000000000"),
                asset("gallery/b.jpg", sha256="b" * 64, phash="0000000000000003"),
            ],
            50,
        )
        self.assertEqual(len(pairs), 1)

    def test_vpdq_similarity_is_bidirectional(self) -> None:
        same = "0" * 64
        other = "f" * 64
        left, right = vpdq_similarity(
            [(same, 100), (other, 100)],
            [(same, 100)],
            distance=0,
        )
        self.assertEqual(left, 0.5)
        self.assertEqual(right, 1.0)

    def test_slider_gets_stricter_to_the_right(self) -> None:
        loose = thresholds(0)
        strict = thresholds(99)
        self.assertGreater(loose["phash"], strict["phash"])
        self.assertLess(loose["minimum_similarity"], strict["minimum_similarity"])

    def test_matching_vpdq_frames_create_video_pair(self) -> None:
        shared = "1234" * 16
        frame_data = json.dumps([{"h": shared, "q": 100, "t": 0}])
        pairs = acquire_pairs(
            [
                asset(
                    "gallery/a.mp4",
                    sha256="a" * 64,
                    media_type="video",
                    extension="mp4",
                    vpdq_hashes=frame_data,
                ),
                asset(
                    "gallery/b.webm",
                    sha256="b" * 64,
                    media_type="video",
                    extension="webm",
                    vpdq_hashes=frame_data,
                ),
            ],
            50,
        )
        self.assertEqual(len(pairs), 1)
        self.assertIn("vPDQ", pairs[0][3])


if __name__ == "__main__":
    unittest.main()
