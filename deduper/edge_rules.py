from __future__ import annotations

from typing import Mapping

from .evidence_store import EvidenceEdge
from .matcher import thresholds


def edge_scores(edge: EvidenceEdge) -> tuple[float | None, float | None, float | None, float | None]:
    phash_score = (
        100 * (1 - int(edge.phash_distance) / 64)
        if edge.phash_distance is not None
        else None
    )
    pdq_score = (
        100 * (1 - int(edge.pdq_distance) / 256)
        if edge.pdq_distance is not None
        else None
    )
    crop_score = float(edge.crop_similarity) if edge.crop_similarity is not None else None
    vpdq_score = None
    if edge.vpdq_left_similarity is not None and edge.vpdq_right_similarity is not None:
        vpdq_score = 100 * min(
            float(edge.vpdq_left_similarity),
            float(edge.vpdq_right_similarity),
        )
    return phash_score, pdq_score, crop_score, vpdq_score


def edge_qualifies(edge: EvidenceEdge, slider: int) -> bool:
    """Apply one truthful qualification contract to every evidence path.

    Algorithm-specific thresholds may nominate a candidate, but no perceptual
    algorithm may bypass the slider's minimum-similarity floor. In particular,
    crop overlap alone is not a special escape hatch at Strict.
    """
    limits: Mapping[str, float | int] = thresholds(slider)
    minimum = float(limits["minimum_similarity"])
    phash_score, pdq_score, crop_score, vpdq_score = edge_scores(edge)

    if (
        edge.phash_distance is not None
        and int(edge.phash_distance) <= int(limits["phash"])
    ):
        strongest = max(
            score for score in (phash_score, pdq_score, crop_score) if score is not None
        )
        if strongest >= minimum:
            return True

    if (
        edge.pdq_distance is not None
        and int(edge.pdq_distance) <= int(limits["pdq"])
        and pdq_score is not None
        and pdq_score >= minimum
    ):
        return True

    if (
        crop_score is not None
        and crop_score / 100 >= float(limits["crop_ratio"])
        and crop_score >= minimum
    ):
        return True

    if (
        vpdq_score is not None
        and edge.vpdq_left_similarity is not None
        and edge.vpdq_right_similarity is not None
        and min(
            float(edge.vpdq_left_similarity),
            float(edge.vpdq_right_similarity),
        ) >= float(limits["vpdq_match"])
        and vpdq_score >= minimum
    ):
        return True

    return False
