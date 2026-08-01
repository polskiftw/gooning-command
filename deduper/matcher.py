from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .models import Asset


PairResult = tuple[str, str, float, str]
ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class MatchingCancelled(Exception):
    """Raised after the latest completed matching stage has already been saved."""


def hamming_hex(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


@dataclass
class _BKNode:
    value: str
    assets: list[Asset] = field(default_factory=list)
    children: dict[int, "_BKNode"] = field(default_factory=dict)


class BKTree:
    def __init__(self):
        self.root: _BKNode | None = None

    def add(self, value: str, asset: Asset) -> None:
        if self.root is None:
            self.root = _BKNode(value, [asset])
            return
        node = self.root
        while True:
            distance = hamming_hex(value, node.value)
            if distance == 0:
                node.assets.append(asset)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(value, [asset])
                return
            node = child

    def search(self, value: str, radius: int) -> Iterable[tuple[int, Asset]]:
        if self.root is None:
            return []
        results: list[tuple[int, Asset]] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = hamming_hex(value, node.value)
            if distance <= radius:
                results.extend((distance, asset) for asset in node.assets)
            low, high = distance - radius, distance + radius
            stack.extend(child for edge, child in node.children.items() if low <= edge <= high)
        return results


def thresholds(slider: int) -> dict[str, float | int]:
    slider = max(0, min(99, int(slider)))
    strictness = slider / 99
    return {
        "phash": round(18 - strictness * 12),
        "pdq": round(48 - strictness * 25),
        "crop_distance": 18 - strictness * 10,
        "crop_ratio": 0.25 + strictness * 0.35,
        "vpdq_distance": round(45 - strictness * 20),
        "vpdq_match": 0.45 + strictness * 0.4,
        "minimum_similarity": 58 + strictness * 29,
    }


def acquire_pair_stages(
    assets: list[Asset],
    slider: int,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    *,
    include_exact: bool = True,
) -> Iterator[tuple[str, list[PairResult]]]:
    """Yield safe, complete result sets after each matching stage.

    Callers can persist every yielded set. If a later perceptual stage is slow,
    cancelled, or fails, exact (and then image) matches are not lost with it.
    """
    limits = thresholds(slider)
    candidates: dict[tuple[str, str], tuple[float, str]] = {}
    qualified_crop_pairs: set[tuple[str, str]] = set()
    if include_exact:
        _exact_pairs(assets, candidates)
        yield "exact", _select_and_orient(assets, candidates, qualified_crop_pairs, limits)
        _check_cancelled(cancelled)

    _phash_pairs(assets, limits, candidates, progress, cancelled)
    yield "phash", _select_and_orient(assets, candidates, qualified_crop_pairs, limits)
    _check_cancelled(cancelled)

    _pdq_pairs(assets, limits, candidates, progress, cancelled)
    yield "pdq", _select_and_orient(assets, candidates, qualified_crop_pairs, limits)
    _check_cancelled(cancelled)

    _crop_pairs(
        assets,
        limits,
        candidates,
        qualified_crop_pairs,
        progress,
        cancelled,
    )
    yield "images", _select_and_orient(assets, candidates, qualified_crop_pairs, limits)
    _check_cancelled(cancelled)

    _video_pairs(assets, limits, candidates, progress, cancelled)
    yield "complete", _select_and_orient(assets, candidates, qualified_crop_pairs, limits)


def acquire_pairs(assets: list[Asset], slider: int) -> list[PairResult]:
    """Return the final result set; retained for tests and non-UI callers."""
    result: list[PairResult] = []
    for _, result in acquire_pair_stages(assets, slider):
        pass
    return result


def partition_exact_duplicates(
    assets: list[Asset],
) -> tuple[list[Asset], list[tuple[str, str]]]:
    """Remove complete SHA groups from review and choose one survivor per group.

    All members of a repeated-SHA group are withheld from perceptual matching for
    this scan. After NUKE removes the extras, the lone survivor naturally returns
    to perceptual matching on the next scan.
    """
    groups: dict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        if asset.sha256:
            groups[asset.sha256].append(asset)

    withheld: set[str] = set()
    deletions: list[tuple[str, str]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        survivor = max(group, key=_survivor_rank)
        withheld.update(asset.key for asset in group)
        deletions.extend(
            (survivor.key, asset.key)
            for asset in group
            if asset.key != survivor.key
        )

    visual_assets = [asset for asset in assets if asset.key not in withheld]
    deletions.sort()
    return visual_assets, deletions


def _select_and_orient(
    assets: list[Asset],
    candidates: dict[tuple[str, str], tuple[float, str]],
    qualified_crop_pairs: set[tuple[str, str]],
    limits: dict[str, float | int],
) -> list[PairResult]:
    minimum = float(limits["minimum_similarity"])
    selected = {
        keys: details
        for keys, details in candidates.items()
        if details[0] >= minimum or keys in qualified_crop_pairs
    }
    return _orient_duplicate_groups(assets, selected)


def _check_cancelled(cancelled: CancelCallback | None) -> None:
    if cancelled is not None and cancelled():
        raise MatchingCancelled()


def _report(
    progress: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
) -> None:
    if progress is not None and (completed == total or completed % 250 == 0):
        progress(stage, completed, total)


def _orient_duplicate_groups(
    assets: list[Asset],
    candidates: dict[tuple[str, str], tuple[float, str]],
) -> list[tuple[str, str, float, str]]:
    """Create safe groups whose deletion candidates directly match their survivor."""
    if not candidates:
        return []

    asset_by_key = {asset.key: asset for asset in assets}
    parent: dict[str, str] = {}
    neighbors: dict[str, set[str]] = defaultdict(set)

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in candidates:
        union(left, right)
        neighbors[left].add(right)
        neighbors[right].add(left)

    groups: dict[str, set[str]] = defaultdict(set)
    for key in parent:
        groups[find(key)].add(key)

    oriented: list[tuple[str, str, float, str]] = []
    for members in groups.values():
        unassigned = set(members)
        while unassigned:
            survivor = max(
                unassigned,
                key=lambda key: _survivor_rank(asset_by_key[key]),
            )
            deletion_candidates = neighbors[survivor] & unassigned
            for deletion_candidate in deletion_candidates:
                score, reason = candidates[tuple(sorted((survivor, deletion_candidate)))]
                oriented.append(
                    (
                        survivor,
                        deletion_candidate,
                        score,
                        f"automatic survivor; {reason}",
                    )
                )
            unassigned.difference_update(deletion_candidates)
            unassigned.remove(survivor)
    oriented.sort(key=lambda pair: (-pair[2], pair[0], pair[1]))
    return oriented


def _survivor_rank(asset: Asset) -> tuple[int, float, int, int, str]:
    """Prefer resolution, duration, PDQ detail, then file size."""
    pixel_count = int(asset.width or 0) * int(asset.height or 0)
    return (
        pixel_count,
        float(asset.duration or 0),
        int(asset.pdq_quality or 0),
        int(asset.size),
        asset.key,
    )


def _record(
    candidates: dict[tuple[str, str], tuple[float, str]],
    left: Asset,
    right: Asset,
    score: float,
    reason: str,
) -> None:
    if left.key == right.key:
        return
    key = tuple(sorted((left.key, right.key)))
    current = candidates.get(key)
    if current is None or score > current[0]:
        candidates[key] = (round(min(100.0, score), 2), reason)


def _exact_pairs(
    assets: list[Asset],
    candidates: dict[tuple[str, str], tuple[float, str]],
) -> None:
    groups: dict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        if asset.sha256:
            groups[asset.sha256].append(asset)
    for group in groups.values():
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                _record(candidates, left, right, 100, "exact SHA-256 match")


def _phash_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> None:
    tree = BKTree()
    radius = int(limits["phash"])
    for index, asset in enumerate(assets, 1):
        _check_cancelled(cancelled)
        if not asset.phash or asset.vpdq_hashes:
            _report(progress, "pHash", index, len(assets))
            continue
        for distance, other in tree.search(asset.phash, radius):
            phash_score = 100 * (1 - distance / 64)
            pdq_score = 0.0
            if asset.pdq_hash and other.pdq_hash:
                pdq_distance = hamming_hex(asset.pdq_hash, other.pdq_hash)
                pdq_score = 100 * (1 - pdq_distance / 256)
            crop_score = crop_similarity(asset.crop_hashes, other.crop_hashes, float(limits["crop_distance"]))
            score = max(phash_score, pdq_score, crop_score)
            reason = (
                f"visual match: pHash {phash_score:.0f}%, "
                f"PDQ {pdq_score:.0f}%, crop {crop_score:.0f}%"
            )
            _record(candidates, asset, other, score, reason)
        tree.add(asset.phash, asset)
        _report(progress, "pHash", index, len(assets))


def _pdq_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> None:
    pdq_tree = BKTree()
    pdq_radius = int(limits["pdq"])
    for index, asset in enumerate(assets, 1):
        _check_cancelled(cancelled)
        if not asset.pdq_hash or asset.vpdq_hashes:
            _report(progress, "PDQ", index, len(assets))
            continue
        for distance, other in pdq_tree.search(asset.pdq_hash, pdq_radius):
            score = 100 * (1 - distance / 256)
            _record(candidates, asset, other, score, f"Meta PDQ match: {score:.0f}%")
        pdq_tree.add(asset.pdq_hash, asset)
        _report(progress, "PDQ", index, len(assets))


def _crop_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    qualified_crop_pairs: set[tuple[str, str]],
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> None:
    """Find crop matches independently instead of requiring a pHash candidate first."""
    tree = BKTree()
    parsed_by_key: dict[str, list[str]] = {}
    radius = int(float(limits["crop_distance"]))
    required_ratio = float(limits["crop_ratio"])

    for index, asset in enumerate(assets, 1):
        _check_cancelled(cancelled)
        if not asset.crop_hashes or asset.vpdq_hashes:
            _report(progress, "crop-resistant", index, len(assets))
            continue
        segment_hashes = _parse_crop_hashes(asset.crop_hashes)
        if not segment_hashes:
            _report(progress, "crop-resistant", index, len(assets))
            continue
        parsed_by_key[asset.key] = segment_hashes

        possible: dict[str, Asset] = {}
        for segment_hash in set(segment_hashes):
            for _, other in tree.search(segment_hash, radius):
                possible[other.key] = other

        for other in possible.values():
            score = crop_similarity_values(
                segment_hashes,
                parsed_by_key[other.key],
                radius,
            )
            if score / 100 < required_ratio:
                continue
            key = tuple(sorted((asset.key, other.key)))
            qualified_crop_pairs.add(key)
            _record(
                candidates,
                asset,
                other,
                score,
                (
                    f"crop-resistant match: {score:.0f}% segment overlap "
                    f"(required {required_ratio:.0%})"
                ),
            )

        for segment_hash in set(segment_hashes):
            tree.add(segment_hash, asset)
        _report(progress, "crop-resistant", index, len(assets))


def crop_similarity(left_json: str | None, right_json: str | None, cutoff: float) -> float:
    if not left_json or not right_json:
        return 0.0
    left = _parse_crop_hashes(left_json)
    right = _parse_crop_hashes(right_json)
    return crop_similarity_values(left, right, cutoff)


def _parse_crop_hashes(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def crop_similarity_values(left: list[str], right: list[str], cutoff: float) -> float:
    if not left or not right:
        return 0.0
    left_matches = sum(
        1 for value in left if min(hamming_hex(value, other) for other in right) <= cutoff
    )
    right_matches = sum(
        1 for value in right if min(hamming_hex(value, other) for other in left) <= cutoff
    )
    return 100 * min(left_matches / len(left), right_matches / len(right))


def _video_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> None:
    videos = [asset for asset in assets if asset.vpdq_hashes]
    token_index: dict[tuple[int, str], list[int]] = defaultdict(list)
    parsed: list[list[tuple[str, int]]] = []
    for index, asset in enumerate(videos):
        _check_cancelled(cancelled)
        frames = [
            (str(frame["h"]), int(frame.get("q", 100)))
            for frame in json.loads(asset.vpdq_hashes or "[]")
            if isinstance(frame, dict) and frame.get("h")
        ]
        parsed.append(frames)
        tokens: set[tuple[int, str]] = set()
        for frame_hash, quality in frames:
            if quality < 35:
                continue
            for band in range(16):
                tokens.add((band, frame_hash[band * 4 : band * 4 + 4]))

        # Count seeds only for this asset instead of materializing every possible
        # pair for the entire library. Random videos commonly share one 16-bit
        # token; real frame overlap shares several. Requiring stronger evidence
        # before full verification removes the combinatorial memory explosion.
        seed_counts: dict[int, int] = defaultdict(int)
        for token in tokens:
            for other_index in token_index.get(token, ()):
                seed_counts[other_index] += 1

        for other_index, shared_seeds in seed_counts.items():
            other_frames = parsed[other_index]
            shorter = min(len(frames), len(other_frames))
            required_seeds = max(1, min(8, math.ceil(shorter * 0.2)))
            if shared_seeds < required_seeds:
                continue
            other = videos[other_index]
            if asset.sha256 and asset.sha256 == other.sha256:
                continue
            left_pct, right_pct = vpdq_similarity(
                other_frames,
                frames,
                int(limits["vpdq_distance"]),
            )
            required = float(limits["vpdq_match"])
            if min(left_pct, right_pct) >= required:
                score = 100 * min(left_pct, right_pct)
                _record(
                    candidates,
                    other,
                    asset,
                    score,
                    f"vPDQ frames: {left_pct:.0%} / {right_pct:.0%}",
                )

        for token in tokens:
            token_index[token].append(index)
        _report(progress, "vPDQ", index + 1, len(videos))


def vpdq_similarity(
    left_frames: list[tuple[str, int]],
    right_frames: list[tuple[str, int]],
    distance: int,
    quality_floor: int = 35,
) -> tuple[float, float]:
    left = list({value for value, quality in left_frames if quality >= quality_floor})
    right = list({value for value, quality in right_frames if quality >= quality_floor})
    if not left or not right:
        return 0.0, 0.0

    left_matched = sum(
        1 for value in left if any(hamming_hex(value, other) <= distance for other in right)
    )
    right_matched = sum(
        1 for value in right if any(hamming_hex(value, other) <= distance for other in left)
    )
    return left_matched / len(left), right_matched / len(right)
