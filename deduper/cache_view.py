from __future__ import annotations

from collections.abc import Iterable

from .evidence_qualification import qualified_edge_rows
from .evidence_store import EvidenceStore
from .matcher import _orient_duplicate_groups
from .models import Asset


def _edge_score_and_reason(row) -> tuple[float, str]:
    scores: list[tuple[float, str]] = []
    if row["phash_distance"] is not None:
        distance = int(row["phash_distance"])
        scores.append((100 * (1 - distance / 64), f"pHash distance {distance}"))
    if row["pdq_distance"] is not None:
        distance = int(row["pdq_distance"])
        scores.append((100 * (1 - distance / 256), f"PDQ distance {distance}"))
    if row["crop_similarity"] is not None:
        score = float(row["crop_similarity"])
        scores.append((score, f"crop overlap {score:.0f}%"))
    if (
        row["vpdq_left_similarity"] is not None
        and row["vpdq_right_similarity"] is not None
    ):
        left = float(row["vpdq_left_similarity"])
        right = float(row["vpdq_right_similarity"])
        score = 100 * min(left, right)
        scores.append((score, f"vPDQ frames {left:.0%} / {right:.0%}"))
    if not scores:
        return 0.0, "certified cached match"
    score, strongest = max(scores, key=lambda item: item[0])
    details = ", ".join(reason for _, reason in scores)
    return round(min(100.0, score), 2), f"certified cache: {details}; strongest {strongest}"


def cached_pairs_for_slider(
    evidence: EvidenceStore,
    assets: Iterable[Asset],
    slider: int,
) -> list[tuple[str, str, float, str]]:
    """Build stable oriented review pairs from certified cached edges.

    The requested slider must be inside the completely indexed range. Rows from
    the legacy observation writer have no qualification record and are excluded.
    """
    value = max(0, min(99, int(slider)))
    boundary = evidence.loosest_complete_slider()
    if boundary is None:
        raise ValueError("no slider positions are certified yet")
    if value < boundary:
        raise ValueError(
            f"slider {value} is not certified; loosest available position is {boundary}"
        )

    materialized = list(assets)
    live_keys = {asset.key for asset in materialized if not asset.deleted}
    candidates: dict[tuple[str, str], tuple[float, str]] = {}
    for row in qualified_edge_rows(evidence, value):
        left = str(row["left_key"])
        right = str(row["right_key"])
        if left not in live_keys or right not in live_keys:
            continue
        score, reason = _edge_score_and_reason(row)
        candidates[(left, right)] = (score, reason)

    return _orient_duplicate_groups(materialized, candidates)
