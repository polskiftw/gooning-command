from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable

from .matcher import BKTree, crop_similarity_values, hamming_hex, thresholds, vpdq_similarity
from .models import Asset


PairResult = tuple[str, str, float, str]


def acquire_focused_pairs(
    assets: Iterable[Asset],
    focus_keys: Iterable[str],
    slider: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> list[PairResult]:
    """Exhaustively match focus assets against the complete live library.

    Existing assets are indexed once, then only added/replaced assets are used as
    queries. Focus-to-focus pairs are emitted once. The returned relationships
    are deliberately unoriented; evidence capture only needs stable key pairs.
    """
    materialized = [asset for asset in assets if not asset.deleted]
    focus = set(focus_keys)
    limits = thresholds(slider)
    candidates: dict[tuple[str, str], tuple[float, str]] = {}
    qualified_crop: set[tuple[str, str]] = set()

    def check() -> None:
        if cancelled is not None and cancelled():
            raise RuntimeError("focused matching cancelled")

    def record(left: Asset, right: Asset, score: float, reason: str) -> None:
        if left.key == right.key or not ({left.key, right.key} & focus):
            return
        key = tuple(sorted((left.key, right.key)))
        current = candidates.get(key)
        if current is None or score > current[0]:
            candidates[key] = (round(min(100.0, score), 2), reason)

    phash_tree = BKTree()
    pdq_tree = BKTree()
    crop_tree = BKTree()
    crop_by_key: dict[str, list[str]] = {}
    indexed_images: list[Asset] = []
    for asset in materialized:
        if asset.vpdq_hashes:
            continue
        indexed_images.append(asset)
        if asset.phash:
            phash_tree.add(asset.phash, asset)
        if asset.pdq_hash:
            pdq_tree.add(asset.pdq_hash, asset)
        if asset.crop_hashes:
            parsed = [str(item) for item in json.loads(asset.crop_hashes) if item]
            crop_by_key[asset.key] = parsed
            for segment in set(parsed):
                crop_tree.add(segment, asset)

    image_focus = [asset for asset in indexed_images if asset.key in focus]
    for asset in image_focus:
        check()
        if asset.phash:
            for distance, other in phash_tree.search(asset.phash, int(limits["phash"])):
                phash_score = 100 * (1 - distance / 64)
                pdq_score = 0.0
                if asset.pdq_hash and other.pdq_hash:
                    pdq_score = 100 * (1 - hamming_hex(asset.pdq_hash, other.pdq_hash) / 256)
                crop_score = 0.0
                if asset.key in crop_by_key and other.key in crop_by_key:
                    crop_score = crop_similarity_values(
                        crop_by_key[asset.key],
                        crop_by_key[other.key],
                        float(limits["crop_distance"]),
                    )
                record(
                    asset,
                    other,
                    max(phash_score, pdq_score, crop_score),
                    f"visual match: pHash {phash_score:.0f}%, PDQ {pdq_score:.0f}%, crop {crop_score:.0f}%",
                )
        if asset.pdq_hash:
            for distance, other in pdq_tree.search(asset.pdq_hash, int(limits["pdq"])):
                score = 100 * (1 - distance / 256)
                record(asset, other, score, f"Meta PDQ match: {score:.0f}%")
        segments = crop_by_key.get(asset.key, [])
        possible: dict[str, Asset] = {}
        for segment in set(segments):
            for _, other in crop_tree.search(segment, int(float(limits["crop_distance"]))):
                possible[other.key] = other
        for other in possible.values():
            other_segments = crop_by_key.get(other.key, [])
            score = crop_similarity_values(
                segments,
                other_segments,
                float(limits["crop_distance"]),
            )
            if score / 100 < float(limits["crop_ratio"]):
                continue
            key = tuple(sorted((asset.key, other.key)))
            qualified_crop.add(key)
            record(asset, other, score, f"crop-resistant match: {score:.0f}% segment overlap")

    videos = [asset for asset in materialized if asset.vpdq_hashes]
    parsed_videos: dict[str, list[tuple[str, int]]] = {}
    token_index: dict[tuple[int, str], set[str]] = defaultdict(set)
    by_key = {asset.key: asset for asset in videos}
    for asset in videos:
        frames = [
            (str(frame["h"]), int(frame.get("q", 100)))
            for frame in json.loads(asset.vpdq_hashes or "[]")
            if isinstance(frame, dict) and frame.get("h")
        ]
        parsed_videos[asset.key] = frames
        for frame_hash, quality in frames:
            if quality < 35:
                continue
            for band in range(16):
                token_index[(band, frame_hash[band * 4 : band * 4 + 4])].add(asset.key)

    for asset in videos:
        if asset.key not in focus:
            continue
        check()
        possible: set[str] = set()
        for frame_hash, quality in parsed_videos[asset.key]:
            if quality < 35:
                continue
            for band in range(16):
                possible.update(token_index[(band, frame_hash[band * 4 : band * 4 + 4])])
        for other_key in possible:
            if other_key == asset.key:
                continue
            other = by_key[other_key]
            left_pct, right_pct = vpdq_similarity(
                parsed_videos[asset.key],
                parsed_videos[other_key],
                int(limits["vpdq_distance"]),
            )
            if min(left_pct, right_pct) < float(limits["vpdq_match"]):
                continue
            score = 100 * min(left_pct, right_pct)
            record(asset, other, score, f"vPDQ frames: {left_pct:.0%} / {right_pct:.0%}")

    minimum = float(limits["minimum_similarity"])
    return [
        (left, right, score, reason)
        for (left, right), (score, reason) in sorted(candidates.items())
        if score >= minimum or (left, right) in qualified_crop
    ]
