from __future__ import annotations

import json
from collections.abc import Iterable

from .evidence_store import EvidenceEdge, EvidenceStore
from .matcher import crop_similarity, hamming_hex, thresholds, vpdq_similarity
from .models import Asset

EVIDENCE_PHASH = 1
EVIDENCE_PDQ = 2
EVIDENCE_CROP = 4
EVIDENCE_VPDQ = 8


def _vpdq_frames(asset: Asset) -> list[tuple[str, int]]:
    if not asset.vpdq_hashes:
        return []
    parsed = json.loads(asset.vpdq_hashes)
    return [
        (str(frame["h"]), int(frame.get("q", 100)))
        for frame in parsed
        if isinstance(frame, dict) and frame.get("h")
    ]


def evidence_for_pairs(
    assets: Iterable[Asset],
    pairs: Iterable[tuple[str, str, float, str]],
    slider: int,
) -> list[EvidenceEdge]:
    """Measure durable evidence for already-discovered matcher pairs.

    pHash and PDQ are stored as raw Hamming distances. Crop and vPDQ values are
    measured with the current matcher parameters and the parameters are recorded
    in cache state by ``capture_pair_evidence``. This makes the observations safe
    to retain without claiming they are complete for other slider positions.
    """
    asset_by_key = {asset.key: asset for asset in assets}
    limits = thresholds(slider)
    crop_cutoff = float(limits["crop_distance"])
    vpdq_distance = int(limits["vpdq_distance"])
    edges: list[EvidenceEdge] = []

    seen: set[tuple[str, str]] = set()
    for left_key, right_key, _, _ in pairs:
        pair_key = tuple(sorted((left_key, right_key)))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        left = asset_by_key.get(left_key)
        right = asset_by_key.get(right_key)
        if left is None or right is None:
            continue

        phash_distance = None
        pdq_distance = None
        crop_score = None
        vpdq_left = None
        vpdq_right = None
        mask = 0

        if left.phash and right.phash:
            phash_distance = hamming_hex(left.phash, right.phash)
            mask |= EVIDENCE_PHASH
        if left.pdq_hash and right.pdq_hash:
            pdq_distance = hamming_hex(left.pdq_hash, right.pdq_hash)
            mask |= EVIDENCE_PDQ
        if left.crop_hashes and right.crop_hashes:
            crop_score = crop_similarity(left.crop_hashes, right.crop_hashes, crop_cutoff)
            mask |= EVIDENCE_CROP
        if left.vpdq_hashes and right.vpdq_hashes:
            vpdq_left, vpdq_right = vpdq_similarity(
                _vpdq_frames(left),
                _vpdq_frames(right),
                vpdq_distance,
            )
            mask |= EVIDENCE_VPDQ

        if mask:
            edges.append(
                EvidenceEdge(
                    left_key=left_key,
                    right_key=right_key,
                    phash_distance=phash_distance,
                    pdq_distance=pdq_distance,
                    crop_similarity=crop_score,
                    vpdq_left_similarity=vpdq_left,
                    vpdq_right_similarity=vpdq_right,
                    evidence_mask=mask,
                )
            )
    return edges


def capture_pair_evidence(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    pairs: Iterable[tuple[str, str, float, str]],
    slider: int,
) -> int:
    """Persist observations from the current matcher without unlocking the slider."""
    materialized_pairs = list(pairs)
    edges = evidence_for_pairs(assets, materialized_pairs, slider)
    count = evidence.upsert_edges(edges)
    limits = thresholds(slider)
    evidence.set_state("last_observed_slider", str(max(0, min(99, int(slider)))))
    evidence.set_state("last_observed_crop_cutoff", str(float(limits["crop_distance"])))
    evidence.set_state("last_observed_vpdq_distance", str(int(limits["vpdq_distance"])))
    evidence.set_state("observed_edge_count", str(evidence.edge_count()))
    # These are observations from the legacy matcher, not proof that any slider
    # range is complete. Never move ``loosest_complete_slider`` here.
    return count
