from __future__ import annotations

import unittest

from deduper.models import Asset
from deduper.survivor_orientation import orient_duplicate_groups, partition_exact_duplicates
from deduper.survivor_policy import SurvivorPolicy


def asset(
    key: str,
    *,
    size: int,
    width: int,
    height: int,
    duration: float = 0,
    pdq_quality: int = 0,
    sha256: str | None = None,
) -> Asset:
    return Asset(
        key=key,
        size=size,
        etag=f"etag-{key}",
        last_modified="2026-08-06T00:00:00+00:00",
        media_type="image",
        extension="jpg",
        width=width,
        height=height,
        duration=duration,
        pdq_quality=pdq_quality,
        sha256=sha256,
    )


class SurvivorOrientationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.small_large_file = asset("large-file", size=900, width=100, height=100)
        self.large_resolution = asset("large-resolution", size=100, width=1000, height=1000)
        self.candidates = {
            tuple(sorted((self.small_large_file.key, self.large_resolution.key))): (
                88.0,
                "visual",
            )
        }

    def test_resolution_policy_keeps_highest_resolution_on_left(self) -> None:
        rows = orient_duplicate_groups(
            [self.small_large_file, self.large_resolution],
            self.candidates,
            SurvivorPolicy.RESOLUTION,
        )
        self.assertEqual(rows[0][0], "large-resolution")
        self.assertEqual(rows[0][1], "large-file")

    def test_file_size_policy_keeps_largest_file_on_left(self) -> None:
        rows = orient_duplicate_groups(
            [self.small_large_file, self.large_resolution],
            self.candidates,
            SurvivorPolicy.FILE_SIZE,
        )
        self.assertEqual(rows[0][0], "large-file")
        self.assertEqual(rows[0][1], "large-resolution")

    def test_exact_sha_uses_same_policy_as_visual_families(self) -> None:
        first = asset("first", size=1000, width=100, height=100, sha256="same")
        second = asset("second", size=100, width=1000, height=1000, sha256="same")

        _, by_size = partition_exact_duplicates(
            [first, second],
            SurvivorPolicy.FILE_SIZE,
        )
        _, by_resolution = partition_exact_duplicates(
            [first, second],
            SurvivorPolicy.RESOLUTION,
        )

        self.assertEqual(by_size, [("first", "second")])
        self.assertEqual(by_resolution, [("second", "first")])

    def test_preview_rows_remain_lowest_similarity_first(self) -> None:
        third = asset("third", size=50, width=50, height=50)
        candidates = {
            tuple(sorted((self.large_resolution.key, self.small_large_file.key))): (90.0, "high"),
            tuple(sorted((self.large_resolution.key, third.key))): (70.0, "low"),
        }
        rows = orient_duplicate_groups(
            [self.large_resolution, self.small_large_file, third],
            candidates,
            SurvivorPolicy.RESOLUTION,
        )
        self.assertEqual([row[2] for row in rows], [70.0, 90.0])


if __name__ == "__main__":
    unittest.main()
