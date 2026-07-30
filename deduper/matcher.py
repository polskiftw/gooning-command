from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import Asset


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


def acquire_pairs(assets: list[Asset], slider: int) -> list[tuple[str, str, float, str]]:
    limits = thresholds(slider)
    candidates: dict[tuple[str, str], tuple[float, str]] = {}
    qualified_crop_pairs: set[tuple[str, str]] = set()
    _exact_pairs(assets, candidates)
    _image_pairs(assets, limits, candidates, qualified_crop_pairs)
    _video_pairs(assets, limits, candidates)
    minimum = float(limits["minimum_similarity"])
    selected = {
        keys: details
        for keys, details in candidates.items()
        if details[0] >= minimum or keys in qualified_crop_pairs
    }
    return _orient_duplicate_groups(assets, selected)


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


def _image_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    qualified_crop_pairs: set[tuple[str, str]],
) -> None:
    tree = BKTree()
    radius = int(limits["phash"])
    for asset in assets:
        if not asset.phash or asset.vpdq_hashes:
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

    pdq_tree = BKTree()
    pdq_radius = int(limits["pdq"])
    for asset in assets:
        if not asset.pdq_hash or asset.vpdq_hashes:
            continue
        for distance, other in pdq_tree.search(asset.pdq_hash, pdq_radius):
            score = 100 * (1 - distance / 256)
            _record(candidates, asset, other, score, f"Meta PDQ match: {score:.0f}%")
        pdq_tree.add(asset.pdq_hash, asset)

    _crop_pairs(assets, limits, candidates, qualified_crop_pairs)


def _crop_pairs(
    assets: list[Asset],
    limits: dict[str, float | int],
    candidates: dict[tuple[str, str], tuple[float, str]],
    qualified_crop_pairs: set[tuple[str, str]],
) -> None:
    """Find crop matches independently instead of requiring a pHash candidate first."""
    tree = BKTree()
    parsed_by_key: dict[str, list[str]] = {}
    radius = int(float(limits["crop_distance"]))
    required_ratio = float(limits["crop_ratio"])

    for asset in assets:
        if not asset.crop_hashes or asset.vpdq_hashes:
            continue
        segment_hashes = _parse_crop_hashes(asset.crop_hashes)
        if not segment_hashes:
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
) -> None:
    videos = [asset for asset in assets if asset.vpdq_hashes]
    token_index: dict[tuple[int, str], set[int]] = defaultdict(set)
    parsed: list[list[tuple[str, int]]] = []
    for index, asset in enumerate(videos):
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
        for token in tokens:
            token_index[token].add(index)

    possible: set[tuple[int, int]] = set()
    for matches in token_index.values():
        ordered = sorted(matches)
        for position, left_index in enumerate(ordered):
            for right_index in ordered[position + 1 :]:
                possible.add((left_index, right_index))

    for left_index, right_index in possible:
        left_frames = parsed[left_index]
        right_frames = parsed[right_index]
        left_pct, right_pct = vpdq_similarity(
            left_frames,
            right_frames,
            int(limits["vpdq_distance"]),
        )
        required = float(limits["vpdq_match"])
        if min(left_pct, right_pct) >= required:
            score = 100 * min(left_pct, right_pct)
            _record(
                candidates,
                videos[left_index],
                videos[right_index],
                score,
                f"vPDQ frames: {left_pct:.0%} / {right_pct:.0%}",
            )


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
